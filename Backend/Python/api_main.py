"""
API principal do BridgeMedAI.

Este módulo expõe os endpoints HTTP do backend local do projeto BridgeMedAI,
responsáveis por:

- verificar o estado da API;
- executar pesquisa semântica sobre fontes normativas indexadas;
- gerar respostas RAG (Retrieval-Augmented Generation) com base em contexto
  regulatório recuperado previamente.

A documentação automática gerada pelo FastAPI (Swagger UI e ReDoc) baseia-se
principalmente em:

- metadados da instância FastAPI;
- modelos Pydantic com descrições e exemplos;
- docstrings das funções;
- argumentos `summary`, `description`, `response_description` e `responses`
  definidos em cada endpoint.

Este ficheiro deve permanecer focado na camada HTTP/API.
A lógica de negócio associada à pesquisa e geração de respostas encontra-se
isolada no módulo `api_rag_service`.
"""

from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Path as FPath,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator

from api_rag_service import search_question, answer_question

from api_user_validation_service import build_user_validation_matrix

from api_regulatory_service import (
    analyze_device,
    collect_answers,
    generate_document,
    get_generated_path,
    session_state,
    set_custom_template,
    skip_remaining_and_generate,
    start_collection,
)
from api_auth_service import (
    AuthUser,
    approve_specialist,
    authenticate,
    consume_admin_invite,
    decode_token,
    generate_admin_invite,
    get_credential_file,
    get_specialist_profile,
    get_user_by_id,
    latest_submission_round,
    list_admin_invites,
    list_credentials,
    list_notifications,
    list_specialist_queue,
    list_users,
    register_specialist,
    register_user,
    reject_specialist,
    resubmit_specialist,
    store_credential,
    update_specialist_profile,
)


from api_traceability_service import (
    init_traceability_schema,
    list_all_traceability_entries,
    list_traceability_entries,
    log_chat_trace,
    log_regulatory_analysis_trace,
    log_regulatory_document_trace,
    request_specialist_review,
    update_traceability_review,
    update_traceability_review_admin,
    update_user_validation_feedback,
)

from api_template_registry import (
    RegistryError,
    get_record,
    get_registry_meta,
    get_template_file_path,
    index_templates,
    is_indexed,
    list_categories,
    list_tags,
    list_templates,
    reload_registry,
    search_templates,
)

from api_document_orchestrator import (
    orchestrator_taxonomy,
    suggest_templates,
)

from api_context_memory import (
    canonical_field_keys,
    create_instance as cm_create_instance,
    create_profile as cm_create_profile,
    delete_field as cm_delete_field,
    delete_instance as cm_delete_instance,
    delete_profile as cm_delete_profile,
    extract_fields_from_text,
    get_instance as cm_get_instance,
    get_or_create_profile_for_conversation,
    get_profile as cm_get_profile,
    get_profile_snapshot,
    init_context_memory_schema,
    list_fields as cm_list_fields,
    list_instances as cm_list_instances,
    list_profiles as cm_list_profiles,
    recompute_documentation_state,
    set_field as cm_set_field,
    templates_using_field,
    update_instance as cm_update_instance,
    update_profile_core,
)

from api_autofill_engine import (
    AutofillError,
    autofill_all_for_profile,
    autofill_instance,
    get_generated_file_path,
)

from api_workflow_engine import (
    apply_workflow,
    get_template_dependency_view,
    workflow_for_profile,
)

from api_chat_questionnaire import (
    answer_current_question,
    cancel_session as questionnaire_cancel,
    get_session_state as questionnaire_state,
    start_questionnaire,
)

# ---------------------------------------------------------------------------
# Metadados OpenAPI por tags
# ---------------------------------------------------------------------------
openapi_tags = [
    {
        "name": "Sistema",
        "description": (
            "Endpoints utilitários para verificação do estado do serviço e "
            "descoberta inicial da API."
        ),
    },
    {
        "name": "Pesquisa",
        "description": (
            "Endpoints de retrieval semântico que devolvem fontes normativas "
            "relevantes sem gerar uma resposta final."
        ),
    },
    {
        "name": "Chat",
        "description": (
            "Endpoints de geração assistida com RAG, combinando retrieval e "
            "resposta textual fundamentada."
        ),
    },
    {
        "name": "Regulatório",
        "description": (
            "Fluxo guiado em três passos: análise regulatória do dispositivo, "
            "recolha de informação em falta e preenchimento do Plano PMCF em .docx."
        ),
    },
    {
        "name": "Autenticação",
        "description": (
            "Registo de users e especialistas, login, gestão do perfil do "
            "especialista e resubmissão de credenciais após rejeição."
        ),
    },
    {
        "name": "Administração",
        "description": (
            "Operações restritas a administradores: fila de aprovação de "
            "especialistas, gestão de convites e listagem global de utilizadores."
        ),
    },
    
    {
        "name": "Rastreabilidade",
        "description": (
            "Endpoints da matriz de rastreabilidade para registo e revisão "
            "das interações do chatbot."
        ),
    },
    {
        "name": "Templates",
        "description": (
            "Catálogo de templates regulatórios (Backend/templates/registry.json) "
            "e descoberta semântica para o Regulatory Documentation Copilot."
        ),
    },
    {
        "name": "Copilot",
        "description": (
            "Document Orchestrator — sugestões contextuais de templates a partir "
            "da conversa atual. Não substitui /chat: é chamado em paralelo."
        ),
    },
    {
        "name": "Memória",
        "description": (
            "Context Memory — perfis de produto, campos extraídos, instâncias de "
            "documentos e estado documental persistidos por utilizador/conversa."
        ),
    },
    {
        "name": "Workflow",
        "description": (
            "Multi-document workflows — grafo de dependências entre templates, "
            "path recomendado por classe MDR / uso de IA / software, e validação "
            "de dependências em falta."
        ),
    },
]


# ---------------------------------------------------------------------------
# Configuração principal da aplicação FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="BridgeMedAI API",
    version="1.1.0",
    summary="API local para pesquisa semântica e geração de respostas regulatórias com RAG.",
    description=(
        "API local do projeto BridgeMedAI para suporte à conformidade regulatória "
        "de dispositivos médicos com IA.\n\n"
        "Esta API permite:\n"
        "- verificar o estado do serviço;\n"
        "- pesquisar excertos normativos relevantes com base em embeddings locais;\n"
        "- gerar respostas fundamentadas com base em fontes recuperadas.\n\n"
        "O backend foi desenhado para trabalhar com documentos regulatórios já "
        "processados e indexados, incluindo regulamentos como o MDR e o AI Act.\n\n"
        "A documentação interativa está disponível em `/docs` (Swagger UI) e "
        "`/redoc` (ReDoc)."
    ),
    contact={
        "name": "BridgeMedAI",
    },
    license_info={
        "name": "Uso académico / protótipo de investigação",
    },
    openapi_tags=openapi_tags,
)


@app.on_event("startup")
def startup_init() -> None:
    try:
        init_traceability_schema()
    except Exception:
        pass
    try:
        init_context_memory_schema()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Configuração de CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # em produção, restringir explicitamente
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Modelos base / utilitários
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    """
    Modelo de erro padronizado devolvido pela API.
    """

    detail: str = Field(
        ...,
        description="Descrição legível do erro ocorrido.",
        examples=[
            "A pergunta não pode estar vazia.",
            "Não foi possível gerar resposta com o contexto disponível.",
            "Erro interno durante o processo de pesquisa semântica.",
        ],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "Não foi possível gerar resposta com o contexto disponível."
            }
        }
    }


class HealthResponse(BaseModel):
    """
    Resposta simples de estado da API.
    """

    status: str = Field(
        ...,
        description="Estado atual da API.",
        examples=["ok"],
    )
    service: str = Field(
        ...,
        description="Nome lógico do serviço.",
        examples=["BridgeMedAI API"],
    )
    version: str = Field(
        ...,
        description="Versão atual da API.",
        examples=["1.1.0"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "service": "BridgeMedAI API",
                "version": "1.1.0",
            }
        }
    }


# ---------------------------------------------------------------------------
# Modelos Pydantic de pedidos e respostas
# ---------------------------------------------------------------------------

class ConversationMessage(BaseModel):
    role: str = Field(..., description="Role da mensagem: user ou assistant.")
    content: str = Field(..., min_length=1, description="Conteúdo textual da mensagem.")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"user", "assistant"}:
            raise ValueError("Role inválida. Use 'user' ou 'assistant'.")
        return cleaned

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("O conteúdo da mensagem não pode estar vazio.")
        return cleaned


class QuestionRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description=(
            "Pergunta do utilizador em linguagem natural. "
            "Será analisada para identificar a intenção, os documentos-alvo "
            "e as fontes normativas potencialmente relevantes."
        ),
        
        examples=[
            "Que regulamentos preciso de cumprir para um dispositivo médico com IA?",
            "Como classificar um termómetro não invasivo segundo o MDR?",
            "Que documentação técnica é exigida pelo MDR?",
        ],
    )
    
    conversation_id: Optional[str] = Field(
        default=None,
        description="Identificador da conversa no frontend para rastreabilidade.",
    )
    
    history: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Últimas mensagens da conversa.",
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A pergunta não pode estar vazia.")
        return cleaned


class SourceItem(BaseModel):
    """
    Representa uma fonte normativa individual recuperada pelo motor de pesquisa.
    """

    citation_label: str = Field(
        ...,
        description="Etiqueta de citação usada para identificar a fonte normativa.",
        examples=["MDR Artigo 10", "AI_ACT Artigo 16", "MDR ANEXO VIII Regra 1"],
    )
    short_name: str = Field(
        ...,
        description="Nome curto do documento de origem da fonte.",
        examples=["MDR", "AI_ACT"],
    )
    section_type: str = Field(
        ...,
        description="Tipo de secção normativa recuperada.",
        examples=["article", "annex", "rule", "point"],
    )
    section_number: str = Field(
        ...,
        description="Número ou identificador da secção no documento.",
        examples=["Artigo 10", "ANEXO VIII", "Regra 1"],
    )
    section_title: str = Field(
        ...,
        description="Título legível da secção normativa.",
        examples=[
            "Obrigações gerais dos fabricantes",
            "Regras de classificação",
            "Documentação técnica",
        ],
    )
    page_start: Optional[int] = Field(
        default=None,
        description="Página inicial da secção ou excerto no documento fonte.",
        examples=[12],
    )
    page_end: Optional[int] = Field(
        default=None,
        description="Página final da secção ou excerto no documento fonte.",
        examples=[14],
    )
    score_adjusted: float = Field(
        ...,
        description=(
            "Score semântico ajustado após aplicação das heurísticas de ranking. "
            "Quanto maior, mais relevante tende a ser a fonte para a pergunta."
        ),
        examples=[0.7421],
    )


class SearchResponse(BaseModel):
    """
    Resposta devolvida pelo endpoint de pesquisa semântica.
    """

    intent: str = Field(
        ...,
        description="Intenção inferida automaticamente a partir da pergunta.",
        examples=[
            "regulatory_scope",
            "classification_risk",
            "documentation",
            "document_generation",
            "conformity_procedure",
            "requirement_lookup",
        ],
    )
    target_docs: List[str] = Field(
        ...,
        description="Documentos-alvo identificados pelo sistema para orientar a pesquisa.",
        examples=[["MDR"], ["MDR", "AI_ACT"]],
    )
    results: List[SourceItem] = Field(
        ...,
        description="Lista de fontes normativas recuperadas e ordenadas por relevância.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "intent": "documentation",
                "target_docs": ["MDR"],
                "results": [
                    {
                        "citation_label": "MDR ANEXO II",
                        "short_name": "MDR",
                        "section_type": "annex",
                        "section_number": "ANEXO II",
                        "section_title": "Documentação técnica",
                        "page_start": 98,
                        "page_end": 104,
                        "score_adjusted": 0.7134,
                    }
                ],
            }
        }
    }


class ChatResponse(BaseModel):
    """
    Resposta devolvida pelo endpoint de chat RAG.
    """

    intent: str = Field(
        ...,
        description="Intenção inferida automaticamente a partir da pergunta.",
        examples=["regulatory_scope", "classification_risk", "document_generation", "documentation", "conformity_procedure", "requirement_lookup"],
    )
    target_docs: List[str] = Field(
        ...,
        description="Documentos-alvo considerados mais relevantes para a resposta.",
        examples=[["MDR"], ["MDR", "AI_ACT"]],
    )
    retrieved_sources: List[SourceItem] = Field(
        ...,
        description="Fontes inicialmente recuperadas pelo motor de pesquisa semântica.",
    )
    generation_sources: List[SourceItem] = Field(
        ...,
        description="Fontes efetivamente utilizadas para construir a resposta final.",
    )
    answer: str = Field(
        ...,
        description=(
            "Resposta textual final gerada pelo sistema com base nas fontes "
            "normativas selecionadas."
        ),
        examples=[
            "1. Regulamentos principais aplicáveis\n- Regulamento (UE) 2017/745 (MDR)\n\n2. Porque se aplicam\n- ..."
        ],
    )

    document_suggestions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Documentos regulatórios recomendados para o contexto da conversa, "
            "renderizados pelo frontend como cards inline no fim da resposta do assistant. "
            "Cada item tem `template`, `score`, `rationale`, `matched_regulations`, `matched_themes`."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "intent": "regulatory_scope",
                "target_docs": ["MDR", "AI_ACT"],
                "retrieved_sources": [
                    {
                        "citation_label": "MDR Artigo 10",
                        "short_name": "MDR",
                        "section_type": "article",
                        "section_number": "Artigo 10",
                        "section_title": "Obrigações gerais dos fabricantes",
                        "page_start": 23,
                        "page_end": 25,
                        "score_adjusted": 0.8125,
                    }
                ],
                "generation_sources": [
                    {
                        "citation_label": "MDR Artigo 10",
                        "short_name": "MDR",
                        "section_type": "article",
                        "section_number": "Artigo 10",
                        "section_title": "Obrigações gerais dos fabricantes",
                        "page_start": 23,
                        "page_end": 25,
                        "score_adjusted": 0.8125,
                    }
                ],
                "answer": (
                    "1. Regulamentos principais aplicáveis\n"
                    "- Regulamento (UE) 2017/745 (MDR)\n"
                    "- Regulamento (UE) 2024/1689 (AI Act)\n\n"
                    "2. Porque se aplicam\n"
                    "- ..."
                ),
            }
        }
    }


# ---------------------------------------------------------------------------
# Segurança — Bearer JWT + dependências de role
# ---------------------------------------------------------------------------
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    """Extrai o utilizador autenticado do Bearer token. Lança 401 se inválido."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticação em falta.")
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    user_id = payload.get("sub")
    user = get_user_by_id(user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilizador não existe.")
    return user


def require_active(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Qualquer role, mas apenas com status=active."""
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Conta em estado '{user.status}'. Acesso restrito.",
        )
    return user


def require_admin(user: AuthUser = Depends(require_active)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas administradores.")
    return user


def require_chatbot_access(user: AuthUser = Depends(require_active)) -> AuthUser:
    if user.role not in ("user", "specialist", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a users, especialistas e administradores.",
        )
    return user


def require_specialist_self(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Endpoints de especialista (inclui pending/rejected para permitir resubmissão)."""
    if user.role != "specialist":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas especialistas.")
    return user


def _is_pmcf_generation_command(text: Optional[str]) -> bool:
    if not text:
        return False

    t = text.strip().lower()

    informational = [
        "o que ",
        "que deve conter",
        "deve conter",
        "conteúdo",
        "conteudo",
        "estrutura",
        "esqueleto",
        "exemplo de plano",
    ]

    if any(expr in t for expr in informational):
        return False

    has_pmcf = "pmcf" in t or "pcmf" in t

    has_strong_generation_intent = any(expr in t for expr in [
        "preenche",
        "preencher",
        "gera o documento",
        "gerar o documento",
        "cria o documento",
        "criar o documento",
        "faz o documento",
        "fazer o documento",
        "documento pmcf",
        "documento pcmf",
    ])

    return has_pmcf and has_strong_generation_intent


def _looks_like_device_description(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    device_signals = [
        "dispositivo médico",
        "dispositivo medico",
        "software médico",
        "software medico",
        "algoritmo de ia",
        "sensor de",
        "utilização em contexto clínico",
        "utilizacao em contexto clinico",
        "profissionais de saúde",
        "profissionais de saude",
        "finalidade prevista",
        "termómetro",
        "termometro",
        "pacemaker",
        "ressonância magnética",
        "ressonancia magnetica",
        "monitorização",
        "monitorizacao",
        "diagnóstico",
        "diagnostico",
        "não invasivo",
        "nao invasivo",
        "classe de risco",
        "classe i",
        "classe iia",
        "classe iib",
        "classe iii",
    ]

    regulatory_signals = [
        "mdr",
        "classe",
        "risco",
        "anexo viii",
        "regra",
        "diagnóstico",
        "diagnostico",
        "monitorização",
        "monitorizacao",
        "clínico",
        "clinico",
        "médico",
        "medico",
    ]

    has_device_signal = any(s in t for s in device_signals)
    has_regulatory_signal = any(s in t for s in regulatory_signals)

    return len(t) >= 20 and has_device_signal and has_regulatory_signal


def _message_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content", "") or "")
    return str(getattr(msg, "content", "") or "")


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", "") or "").lower()
    return str(getattr(msg, "role", "") or "").lower()


def _extract_referenced_user_message(
    command: str,
    history: Optional[List[Any]],
) -> Optional[str]:
    if not history:
        return None

    t = (command or "").strip().lower()

    ordinal_map = {
        "primeira": 1,
        "primeiro": 1,
        "1ª": 1,
        "1a": 1,
        "1º": 1,
        "segunda": 2,
        "segundo": 2,
        "2ª": 2,
        "2a": 2,
        "2º": 2,
        "terceira": 3,
        "terceiro": 3,
        "3ª": 3,
        "3a": 3,
        "3º": 3,
        "quarta": 4,
        "quarto": 4,
        "4ª": 4,
        "4a": 4,
        "4º": 4,
        "quinta": 5,
        "quinto": 5,
        "5ª": 5,
        "5a": 5,
        "5º": 5,
    }

    user_messages = []
    for msg in history:
        if _message_role(msg) != "user":
            continue

        content = _message_content(msg).strip()
        if not content:
            continue

        if _is_pmcf_generation_command(content):
            continue

        user_messages.append(content)

    for word, position in ordinal_map.items():
        if word in t:
            idx = position - 1
            if 0 <= idx < len(user_messages):
                return user_messages[idx]

    if "última" in t or "ultima" in t or "último" in t or "ultimo" in t:
        return user_messages[-1] if user_messages else None

    return None


def _resolve_regulatory_description(
    description: str,
    history: Optional[List[Any]],
) -> str:
    cleaned = (description or "").strip()

    referenced = _extract_referenced_user_message(cleaned, history)
    if referenced:
        return referenced

    if cleaned and not _is_pmcf_generation_command(cleaned):
        return cleaned

    if history:
        for msg in reversed(history):
            if _message_role(msg) != "user":
                continue

            content = _message_content(msg).strip()
            if not content:
                continue

            if _is_pmcf_generation_command(content):
                continue

            if _looks_like_device_description(content):
                return content

    return cleaned



def _history_dicts_to_messages(
    history: Optional[List[Dict[str, str]]],
) -> List[ConversationMessage]:
    if not history:
        return []

    out: List[ConversationMessage] = []

    for item in history:
        try:
            out.append(ConversationMessage(**item))
        except Exception:
            continue

    return out


def _generate_pmcf_from_chat_command(
    payload: QuestionRequest,
    user: AuthUser,
) -> Dict[str, Any]:
    history_messages = _history_dicts_to_messages(payload.history or [])

    resolved_description = _resolve_regulatory_description(
        payload.question,
        history_messages,
    )

    if not resolved_description or _is_pmcf_generation_command(resolved_description):
        raise ValueError(
            "Para gerar o Plano PMCF preciso de uma descrição anterior do dispositivo. "
            "Descreve primeiro o dispositivo ou faz a análise regulatória inicial."
        )

    analysis_result = analyze_device(
        session_id=None,
        description=resolved_description,
    )

    session_id = analysis_result["session_id"]

    # Gera já o documento, preenchendo o que conseguir e marcando o resto para revisão manual.
    doc_result = skip_remaining_and_generate(session_id)

    answer = (
        f"{doc_result.get('assistant_text', '')}\n\n"
        f"Link de download: {doc_result.get('download_url')}\n"
        f"Ficheiro: {doc_result.get('download_name')}"
    ).strip()

    try:
        log_regulatory_document_trace(
            user_id=user.id,
            conversation_id=payload.conversation_id,
            session_id=session_id,
            step=doc_result.get("step", ""),
            assistant_text=answer,
            download_name=doc_result.get("download_name"),
            filled_fields=doc_result.get("filled_fields", []),
            flagged_fields=doc_result.get("flagged_fields", []),
        )
    except Exception:
        pass

    return {
        "intent": "document_generation",
        "target_docs": ["MDR"],
        "retrieved_sources": [],
        "generation_sources": [],
        "answer": answer,
    }

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/",
    tags=["Sistema"],
    summary="Obter informação inicial da API",
    description=(
        "Endpoint de entrada simples para confirmar que a API está acessível "
        "e indicar os principais caminhos de documentação disponíveis."
    ),
    operation_id="get_api_root",
)
def root():
    """
    Devolve informação introdutória sobre a API e os links principais de documentação.
    """
    return {
        "message": "BridgeMedAI API disponível.",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["Sistema"],
    summary="Verificar estado da API",
    description=(
        "Endpoint simples de verificação de disponibilidade do serviço.\n\n"
        "Pode ser usado pelo frontend ou por scripts de monitorização para "
        "confirmar que a API está em execução e acessível."
    ),
    response_description="Estado atual da API.",
    operation_id="get_health_status",
)
def health() -> HealthResponse:
    """
    Verifica se a API está operacional.
    """
    return HealthResponse(
        status="ok",
        service="BridgeMedAI API",
        version="1.1.0",
    )


@app.post(
    "/search",
    dependencies=[Depends(require_chatbot_access)],
    response_model=SearchResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    tags=["Pesquisa"],
    summary="Pesquisar fontes normativas relevantes",
    description=(
        "Recebe uma pergunta do utilizador e executa o pipeline de pesquisa "
        "semântica sobre embeddings locais.\n\n"
        "O sistema analisa a intenção da pergunta, identifica os documentos-alvo "
        "mais prováveis e devolve uma lista de fontes normativas relevantes "
        "ordenadas por score ajustado.\n\n"
        "Este endpoint é especialmente útil para depuração, inspeção do retrieval "
        "e validação das fontes encontradas antes da geração final."
    ),
    response_description=(
        "Resultado da pesquisa semântica com intenção, documentos-alvo e fontes recuperadas."
    ),
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Pedido inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "A pergunta não pode estar vazia."}
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Erro interno durante o processo de pesquisa semântica.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Erro interno durante o processo de pesquisa semântica."
                    }
                }
            },
        },
    },
    operation_id="post_search_sources",
)
def search_endpoint(payload: QuestionRequest) -> SearchResponse:
    """
    Executa a pesquisa semântica para uma pergunta em linguagem natural.

    Este endpoint não gera uma resposta final em formato conversacional.
    Em vez disso, devolve apenas o resultado intermédio da recuperação de
    fontes, sendo útil para depuração, análise de relevância e inspeção do
    comportamento do motor de retrieval.
    """
    try:
        return search_question(
            payload.question,
            history=payload.history or [],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante o processo de pesquisa semântica.",
        )


@app.post(
    "/chat",
    dependencies=[Depends(require_chatbot_access)],
    response_model=ChatResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    tags=["Chat"],
    summary="Gerar resposta regulatória com RAG",
    description=(
        "Recebe uma pergunta do utilizador e executa o fluxo completo do sistema "
        "RAG do BridgeMedAI.\n\n"
        "O endpoint:\n"
        "1. analisa a pergunta e deteta a intenção;\n"
        "2. recupera fontes normativas relevantes a partir dos embeddings locais;\n"
        "3. seleciona as melhores fontes para geração;\n"
        "4. gera uma resposta textual fundamentada com base nesse contexto.\n\n"
        "A resposta devolvida inclui tanto as fontes recuperadas como as fontes "
        "efetivamente usadas na geração."
    ),
    response_description=(
        "Resposta RAG completa com metadados, fontes recuperadas, fontes de geração e texto final."
    ),
    responses={
        400: {
            "model": ErrorResponse,
            "description": (
                "Pedido inválido ou impossibilidade de gerar resposta por falta "
                "de contexto relevante ou de configuração necessária."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Não foi possível gerar resposta com o contexto disponível."
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Erro interno durante o processo de retrieval ou geração.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Erro interno durante o processo de retrieval ou geração."
                    }
                }
            },
        },
    },
    operation_id="post_chat_answer",
)

def chat_endpoint(
    payload: QuestionRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> ChatResponse:
    try:
        if _is_pmcf_generation_command(payload.question):
            return _generate_pmcf_from_chat_command(payload, user)

        result = answer_question(
            payload.question,
            history=payload.history or [],
        )

        try:
            log_chat_trace(
                user_id=user.id,
                conversation_id=payload.conversation_id,
                question=payload.question,
                answer=result.get("answer", ""),
                intent=result.get("intent"),
                target_docs=result.get("target_docs", []),
                retrieved_sources=result.get("retrieved_sources", []),
                generation_sources=result.get("generation_sources", []),
            )
        except Exception:
            pass

        # Enriquecer a resposta com sugestões de documentos quando a conversa
        # parece regulatória. Falha silenciosa — se algo correr mal aqui o
        # /chat continua a funcionar normalmente.
        try:
            # Pedimos vários candidatos (10) para depois diversificar por
            # categoria — assim se o user mencionou risco + cibersegurança +
            # usability, garantimos pelo menos um de cada e não só Software.
            suggestions_payload = suggest_templates(
                question=payload.question,
                history=payload.history or [],
                n_results=10,
            )
            detected_themes = suggestions_payload.get("detected_themes") or []
            detected_regs = suggestions_payload.get("detected_regulations") or []
            has_signal = bool(detected_themes or detected_regs)

            candidates = []
            for s in suggestions_payload.get("suggestions", []):
                score = s.get("score") or 0
                if has_signal or score >= 0.4:
                    candidates.append(s)

            # Diversificação: round-robin por categoria. Garante que se
            # houver sugestões de Risk Management, Cybersecurity, Usability,
            # etc., aparecem em vez de só repetir Software 5x.
            by_category = {}
            for s in candidates:
                cat = s.get("template", {}).get("category", "_")
                by_category.setdefault(cat, []).append(s)

            diversified = []
            # Primeiro round: 1 por categoria
            for cat_list in by_category.values():
                if cat_list:
                    diversified.append(cat_list.pop(0))
            # Rounds seguintes: enche até atingir o limite
            while len(diversified) < 6:
                made_progress = False
                for cat_list in by_category.values():
                    if cat_list and len(diversified) < 6:
                        diversified.append(cat_list.pop(0))
                        made_progress = True
                if not made_progress:
                    break

            print(f'[DEBUG /chat] candidates={len(candidates)} categories={list(by_category.keys())} diversified={len(diversified)}', flush=True)
            if diversified:
                result["document_suggestions"] = diversified[:6]
                print(f'[DEBUG /chat] sent {len(result["document_suggestions"])} suggestions', flush=True)
        except Exception as _exc:
            print(f'[DEBUG /chat] EXCEPTION in suggestions: {_exc}', flush=True)
            pass

        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante o processo de retrieval ou geração.",
        )


# ---------------------------------------------------------------------------
# Fluxo regulatório guiado (Step 1 / 2 / 3 do PMCF)
# ---------------------------------------------------------------------------
class RegulatoryStartRequest(BaseModel):
    description: str = Field(
        ...,
        min_length=3,
        description="Descrição do dispositivo médico em linguagem natural.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Identificador de sessão a reutilizar; se omisso, é criada nova sessão.",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Identificador da conversa no frontend para rastreabilidade.",
    )
    
    history: Optional[List[ConversationMessage]] = Field(
        default=None,
        description="Histórico recente da conversa para resolver referências contextuais.",
    )

    @field_validator("description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A descrição não pode estar vazia.")
        return cleaned


class RegulatoryConfirmRequest(BaseModel):
    session_id: str = Field(..., description="Identificador da sessão regulatória.")
    accept: bool = Field(
        ...,
        description="Se True, arranca a recolha de informação; se False, encerra o fluxo.",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Identificador da conversa no frontend para rastreabilidade.",
    )


class RegulatoryMessageRequest(BaseModel):
    session_id: str = Field(..., description="Identificador da sessão regulatória.")
    message: str = Field(..., min_length=1, description="Texto livre do utilizador.")
    conversation_id: Optional[str] = Field(
        default=None,
        description="Identificador da conversa no frontend para rastreabilidade.",
    )


class RegulatoryStepResponse(BaseModel):
    """Resposta genérica de qualquer passo do fluxo regulatório."""
    session_id: str
    step: str = Field(..., description="Estado atual da máquina de fluxo.")
    assistant_text: str = Field(..., description="Mensagem textual a apresentar ao utilizador.")
    analysis: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadados estruturados da análise regulatória (Step 1).",
    )
    missing_groups: Optional[Dict[str, List[Dict[str, str]]]] = Field(
        default=None,
        description="Perguntas pendentes agrupadas logicamente (Step 2).",
    )
    still_missing: Optional[List[str]] = Field(
        default=None,
        description="Chaves ainda por responder após mapeamento.",
    )
    filled_fields: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Campos preenchidos automaticamente no documento (Step 3).",
    )
    flagged_fields: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Campos marcados como 'preencher manualmente' (Step 3).",
    )
    download_url: Optional[str] = Field(
        default=None,
        description="Caminho relativo para descarregar o documento final.",
    )
    download_name: Optional[str] = Field(
        default=None,
        description="Nome sugerido do ficheiro para download.",
    )
    pending_action: Optional[str] = Field(
        default=None,
        description="Ação seguinte esperada por parte do utilizador.",
    )
    collected_count: Optional[int] = None
    
    
class TraceabilityEntry(BaseModel):
    id: str
    user_id: str
    conversation_id: Optional[str] = None
    trace_type: str
    question: Optional[str] = None
    answer: Optional[str] = None
    intent: Optional[str] = None

    target_docs: Any = Field(default_factory=list)
    retrieved_sources: Any = Field(default_factory=list)
    generation_sources: Any = Field(default_factory=list)

    regulatory_session_id: Optional[str] = None
    regulatory_step: Optional[str] = None
    download_name: Optional[str] = None
    result: Optional[str] = None
    error_type: Optional[str] = None
    severity: Optional[str] = None
    reviewer_notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    user_feedback_result: Optional[str] = None
    user_feedback_notes: Optional[str] = None
    review_requested: bool = False
    review_requested_at: Optional[str] = None


class TraceabilityReviewRequest(BaseModel):
    result: Optional[str] = Field(default=None, pattern="^(OK|PARCIAL|NOK)?$")
    error_type: Optional[str] = Field(default=None, pattern="^(E1|E2|E3|E4|E5|E6|E7)?$")
    severity: Optional[str] = Field(default=None, pattern="^(baixa|média|alta)?$")
    reviewer_notes: Optional[str] = None
    
class UserValidationFeedbackRequest(BaseModel):
    result: str = Field(..., pattern="^(OK|PARCIAL|NOK)$")
    notes: Optional[str] = None


def _to_response(result: Dict[str, Any]) -> RegulatoryStepResponse:
    return RegulatoryStepResponse(**result)


@app.post(
    "/regulatory/start",
    dependencies=[Depends(require_chatbot_access)],
    response_model=RegulatoryStepResponse,
    status_code=status.HTTP_200_OK,
    tags=["Regulatório"],
    summary="Step 1 — Análise regulatória do dispositivo",
    description=(
        "Recebe a descrição de um dispositivo médico e devolve a análise completa: "
        "tipo de dispositivo, classificação MDR (Anexo VIII) com regra aplicável, "
        "enquadramento no AI Act, obrigações MDR, normas harmonizadas relevantes e "
        "separação entre obrigações pré-mercado e pós-mercado. Termina sempre a "
        "perguntar se o utilizador pretende preencher o Plano PMCF."
    ),
    operation_id="post_regulatory_start",
)

def regulatory_start(
    payload: RegulatoryStartRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> RegulatoryStepResponse:
    try:
        resolved_description = _resolve_regulatory_description(
            payload.description,
            payload.history,
        )

        result = analyze_device(payload.session_id, resolved_description)

        try:
            log_regulatory_analysis_trace(
            user_id=user.id,
            conversation_id=payload.conversation_id,
            question=resolved_description,
            assistant_text=result.get("assistant_text", ""),
            session_id=result.get("session_id", payload.session_id or ""),
            step=result.get("step", ""),
            analysis=result.get("analysis"),
            target_docs=["MDR", "AI_ACT"],
        )
        except Exception:
            pass

        return _to_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro na análise regulatória: {exc}",
        )

@app.post(
    "/regulatory/confirm",
    dependencies=[Depends(require_chatbot_access)],
    response_model=RegulatoryStepResponse,
    status_code=status.HTTP_200_OK,
    tags=["Regulatório"],
    summary="Step 2 — Confirmação do preenchimento do PMCF",
    description=(
        "Após a análise, o utilizador decide se quer prosseguir com o preenchimento. "
        "Se aceitar, o sistema carrega o template e devolve a lista de campos em falta."
    ),
    operation_id="post_regulatory_confirm",
)
def regulatory_confirm(payload: RegulatoryConfirmRequest) -> RegulatoryStepResponse:
    try:
        if not payload.accept:
            return RegulatoryStepResponse(
                session_id=payload.session_id,
                step="closed",
                assistant_text="Sem problema. Se precisares, posso retomar a análise noutra altura.",
                pending_action=None,
            )
        result = start_collection(payload.session_id)
        return _to_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao iniciar recolha: {exc}",
        )


@app.post(
    "/regulatory/message",
    dependencies=[Depends(require_chatbot_access)],
    response_model=RegulatoryStepResponse,
    status_code=status.HTTP_200_OK,
    tags=["Regulatório"],
    summary="Step 2 — Envio de respostas do utilizador",
    description=(
        "Envia o texto livre com as respostas do utilizador. O sistema usa o LLM "
        "para mapear as respostas às chaves em aberto. Pode requerer várias "
        "iterações até todos os campos estarem preenchidos ou marcados."
    ),
    operation_id="post_regulatory_message",
)
def regulatory_message(payload: RegulatoryMessageRequest) -> RegulatoryStepResponse:
    try:
        result = collect_answers(payload.session_id, payload.message)
        return _to_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar a mensagem: {exc}",
        )


@app.post(
    "/regulatory/finalize",
    dependencies=[Depends(require_chatbot_access)],
    response_model=RegulatoryStepResponse,
    status_code=status.HTTP_200_OK,
    tags=["Regulatório"],
    summary="Step 3 — Gerar o documento PMCF final",
    description=(
        "Força o preenchimento do documento mesmo que ainda existam campos em aberto. "
        "Os campos em falta são marcados com '⚠️ Preencher manualmente' no documento."
    ),
    operation_id="post_regulatory_finalize",
)

def regulatory_finalize(
    payload: RegulatoryConfirmRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> RegulatoryStepResponse:
    try:
        result = skip_remaining_and_generate(payload.session_id)

        try:
            log_regulatory_document_trace(
                user_id=user.id,
                conversation_id=payload.conversation_id,
                session_id=result.get("session_id", payload.session_id),
                step=result.get("step", ""),
                assistant_text=result.get("assistant_text", ""),
                download_name=result.get("download_name"),
                filled_fields=result.get("filled_fields", []),
                flagged_fields=result.get("flagged_fields", []),
            )
        except Exception:
            pass

        return _to_response(result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar o documento: {exc}",
        )


@app.post(
    "/regulatory/upload-template",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Regulatório"],
    summary="Carregar um template PMCF personalizado",
    description=(
        "Permite ao utilizador enviar o seu próprio .docx de template. Se omitido, "
        "é usado o template pré-carregado do projeto (Backend/templates/pmcf_template.docx)."
    ),
    operation_id="post_regulatory_upload_template",
)
async def regulatory_upload_template(
    session_id: str, file: UploadFile = File(...)
) -> Dict[str, Any]:
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas ficheiros .docx são aceites.",
        )
    try:
        content = await file.read()
        return set_custom_template(session_id, content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao carregar template: {exc}",
        )


@app.get(
    "/regulatory/state/{session_id}",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Regulatório"],
    summary="Obter estado atual de uma sessão regulatória",
    operation_id="get_regulatory_state",
)
def regulatory_state(session_id: str) -> Dict[str, Any]:
    try:
        return session_state(session_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get(
    "/regulatory/download/{session_id}",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Regulatório"],
    summary="Descarregar o Plano PMCF preenchido",
    operation_id="get_regulatory_download",
)
def regulatory_download(session_id: str = FPath(..., description="Sessão regulatória.")):
    try:
        path = get_generated_path(session_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


@app.get(
    "/traceability",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[TraceabilityEntry],
    tags=["Rastreabilidade"],
    summary="Listar matriz de rastreabilidade do utilizador",
)

def traceability_list(
    limit: int = Query(100, ge=1, le=500),
    conversation_id: Optional[str] = Query(
        default=None,
        description="Filtra a matriz por conversa específica.",
    ),
    user: AuthUser = Depends(require_chatbot_access),
) -> List[TraceabilityEntry]:
    try:
        return list_traceability_entries(
            user_id=user.id,
            limit=limit,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar matriz: {exc}",
        )


@app.get(
    "/user/validation",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Rastreabilidade"],
    summary="Matriz de pré-validação automática do utilizador",
)
def user_validation_matrix(
    limit: int = Query(100, ge=1, le=500),
    conversation_id: Optional[str] = Query(
        default=None,
        description="Filtra por conversa específica.",
    ),
    user: AuthUser = Depends(require_chatbot_access),
) -> List[Dict[str, Any]]:
    try:
        entries = list_traceability_entries(
            user_id=user.id,
            limit=limit,
            conversation_id=conversation_id,
        )
        return build_user_validation_matrix(entries)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar matriz de validação automática: {exc}",
        )


@app.patch(
    "/user/validation/{trace_id}/feedback",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Rastreabilidade"],
    summary="Guardar feedback simples do utilizador sobre uma resposta",
)
def user_validation_feedback(
    trace_id: str,
    payload: UserValidationFeedbackRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return update_user_validation_feedback(
            trace_id=trace_id,
            user_id=user.id,
            result=payload.result,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao guardar feedback do utilizador: {exc}",
        )


@app.post(
    "/user/validation/{trace_id}/request-review",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Rastreabilidade"],
    summary="Enviar uma entrada para revisão de especialista",
)
def user_validation_request_review(
    trace_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return request_specialist_review(
            trace_id=trace_id,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao enviar para especialista: {exc}",
        )



@app.patch(
    "/traceability/{trace_id}",
    dependencies=[Depends(require_chatbot_access)],
    response_model=TraceabilityEntry,
    tags=["Rastreabilidade"],
    summary="Atualizar revisão de uma entrada da matriz",
)
def traceability_update(
    trace_id: str,
    payload: TraceabilityReviewRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> TraceabilityEntry:
    try:
        return update_traceability_review(
            trace_id=trace_id,
            user_id=user.id,
            result=payload.result,
            error_type=payload.error_type,
            severity=payload.severity,
            reviewer_notes=payload.reviewer_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar matriz: {exc}",
        )


# ===========================================================================
# Autenticação
# ===========================================================================
class RegisterUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)


class RegisterSpecialistRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    specialty: str = Field(..., min_length=2)
    institution: str = Field(..., min_length=2)
    country: str = Field(..., min_length=2)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteRegisterRequest(BaseModel):
    token: str = Field(..., min_length=8)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)


class InviteCreateRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=255)


class RejectSpecialistRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class UpdateSpecialistProfileRequest(BaseModel):
    specialty: Optional[str] = None
    institution: Optional[str] = None
    country: Optional[str] = None
    


def _auth_payload(user: AuthUser, token: str, expires_at) -> Dict[str, Any]:
    profile = get_specialist_profile(user.id) if user.role == "specialist" else None
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "status": user.status,
        },
        "specialist_profile": profile,
    }


def _me_payload(user: AuthUser) -> Dict[str, Any]:
    profile = get_specialist_profile(user.id) if user.role == "specialist" else None
    notifications = list_notifications(user.id, limit=5)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "specialist_profile": profile,
        "notifications": notifications,
    }


@app.post("/auth/register-user", tags=["Autenticação"], summary="Registo público de um utilizador normal.")
def auth_register_user(payload: RegisterUserRequest) -> Dict[str, Any]:
    try:
        user = register_user(payload.email, payload.password, payload.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    # Emite token imediatamente (status=active)
    _, token_str, exp = authenticate(payload.email, payload.password)
    return _auth_payload(user, token_str, exp)


@app.post("/auth/register-specialist", tags=["Autenticação"], summary="Registo de um especialista (fica pending).")
async def auth_register_specialist(
    email: EmailStr = Form(...),
    password: str = Form(..., min_length=8),
    full_name: str = Form(..., min_length=2),
    # Os campos abaixo são opcionais — narrativa atual: engenheiro regulatório
    # (consultor MDR/AI Act), não médico. Mantidos para informação extra livre.
    specialty: Optional[str] = Form(default=None, description="(Opcional) Área de especialização regulatória — ex: MDR, AI Act, IEC 62304."),
    institution: Optional[str] = Form(default=None, description="(Opcional) Empresa ou organização."),
    country: Optional[str] = Form(default=None, description="(Opcional) País."),
    credentials: List[UploadFile] = File(..., description="Documentos comprovativos (CV, certificados — .pdf, .jpg, .png)."),
) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tem de carregar pelo menos um documento.")
    try:
        user = register_specialist(
            email=email,
            password=password,
            full_name=full_name,
            specialty=specialty,
            institution=institution,
            country=country,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    for up in credentials:
        try:
            content = await up.read()
            store_credential(user.id, up.filename or "credential", content, up.content_type or "application/octet-stream", 1)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{up.filename}: {exc}")
    user = get_user_by_id(user.id) or user
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "status": user.status,
        },
        "message": "Conta criada em estado 'pending'. Um administrador vai rever as credenciais submetidas.",
    }


@app.post("/auth/login", tags=["Autenticação"], summary="Autenticação com email + password.")
def auth_login(payload: LoginRequest) -> Dict[str, Any]:
    try:
        user, token, exp = authenticate(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return _auth_payload(user, token, exp)


@app.post("/auth/invite-register", tags=["Autenticação"], summary="Registo de admin via convite único.")
def auth_invite_register(payload: InviteRegisterRequest) -> Dict[str, Any]:
    try:
        user = consume_admin_invite(payload.token, payload.email, payload.password, payload.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    _, token, exp = authenticate(payload.email, payload.password)
    return _auth_payload(user, token, exp)


@app.get("/auth/me", tags=["Autenticação"], summary="Perfil do utilizador autenticado.")
def auth_me(user: AuthUser = Depends(get_current_user)) -> Dict[str, Any]:
    return _me_payload(user)


@app.get("/auth/invite/{token}", tags=["Autenticação"], summary="Valida um convite sem o consumir.")
def auth_check_invite(token: str) -> Dict[str, Any]:
    import hashlib as _h
    from datetime import datetime as _dt, timezone as _tz
    th = _h.sha256(token.encode("utf-8")).hexdigest()
    from api_db import db_cursor as _db
    with _db() as cur:
        cur.execute(
            "SELECT expires_at, used_at, note FROM dbo.admin_invites WHERE token_hash = ?",
            th,
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Convite inválido.")
    expires_at, used_at, note = row
    if used_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Este convite já foi utilizado.")
    if expires_at:
        exp_cmp = expires_at.replace(tzinfo=_tz.utc) if expires_at.tzinfo is None else expires_at
        if exp_cmp < _dt.now(_tz.utc):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Este convite expirou.")
    return {"valid": True, "expires_at": expires_at.isoformat() if expires_at else None, "note": note}


# ---------------------------------------------------------------------------
# Especialista (pending/rejected/approved)
# ---------------------------------------------------------------------------
@app.post(
    "/specialist/resubmit",
    tags=["Autenticação"],
    summary="Especialista rejeitado/pending resubmete credenciais.",
)
async def specialist_resubmit(
    specialty: Optional[str] = Form(None),
    institution: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    credentials: List[UploadFile] = File(..., description="Nova(s) credencial(is)."),
    user: AuthUser = Depends(require_specialist_self),
) -> Dict[str, Any]:
    if user.status == "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A conta já está ativa — não é necessária resubmissão.",
        )
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tem de carregar pelo menos um ficheiro.")

    update_specialist_profile(user.id, specialty=specialty, institution=institution, country=country)

    new_round = latest_submission_round(user.id) + 1
    for up in credentials:
        try:
            content = await up.read()
            store_credential(user.id, up.filename or "credential", content, up.content_type or "application/octet-stream", new_round)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{up.filename}: {exc}")

    resubmit_specialist(user.id)
    refreshed = get_user_by_id(user.id) or user
    return {"message": "Nova submissão recebida. A conta voltou ao estado 'pending'.",
            "user": {"id": refreshed.id, "status": refreshed.status}}


@app.get("/specialist/me/credentials", tags=["Autenticação"], summary="Lista credenciais do próprio especialista.")
def specialist_my_credentials(user: AuthUser = Depends(require_specialist_self)) -> List[Dict[str, Any]]:
    return list_credentials(user.id)


# ---------------------------------------------------------------------------
# Administração
# ---------------------------------------------------------------------------
@app.get("/admin/users", tags=["Administração"], summary="Lista todos os utilizadores.")
def admin_users(
    role: Optional[str] = Query(None, pattern="^(user|specialist|admin)$"),
    status_filter: Optional[str] = Query(None, alias="status", pattern="^(active|pending|rejected)$"),
    _: AuthUser = Depends(require_admin),
) -> List[Dict[str, Any]]:
    return list_users(role=role, status=status_filter)


@app.get("/admin/specialist-queue", tags=["Administração"], summary="Fila de especialistas a aprovar.")
def admin_specialist_queue(_: AuthUser = Depends(require_admin)) -> List[Dict[str, Any]]:
    return list_specialist_queue()


@app.post("/admin/specialists/{user_id}/approve", tags=["Administração"], summary="Aprovar especialista pendente.")
def admin_approve_specialist(user_id: str, admin: AuthUser = Depends(require_admin)) -> Dict[str, Any]:
    target = get_user_by_id(user_id)
    if not target or target.role != "specialist":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Especialista não encontrado.")
    approve_specialist(user_id, admin.id)
    return {"message": "Especialista aprovado.", "user_id": user_id}


@app.post("/admin/specialists/{user_id}/reject", tags=["Administração"], summary="Rejeitar especialista com motivo.")
def admin_reject_specialist(user_id: str, payload: RejectSpecialistRequest, admin: AuthUser = Depends(require_admin)) -> Dict[str, Any]:
    target = get_user_by_id(user_id)
    if not target or target.role != "specialist":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Especialista não encontrado.")
    try:
        reject_specialist(user_id, admin.id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"message": "Especialista rejeitado.", "user_id": user_id, "reason": payload.reason}


@app.get("/admin/credentials/{cred_id}/download", tags=["Administração"], summary="Descarregar ficheiro de credencial.")
def admin_download_credential(cred_id: str, _: AuthUser = Depends(require_admin)):
    info = get_credential_file(cred_id)
    if not info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credencial não encontrada.")
    return FileResponse(path=info["file_path"], media_type=info["mime_type"], filename=info["original_filename"])


@app.post("/admin/invites", tags=["Administração"], summary="Gerar novo convite de admin.")
def admin_create_invite(payload: InviteCreateRequest, admin: AuthUser = Depends(require_admin)) -> Dict[str, Any]:
    return generate_admin_invite(created_by=admin.id, note=payload.note)


@app.get("/admin/invites", tags=["Administração"], summary="Listar convites de admin.")
def admin_list_invites(_: AuthUser = Depends(require_admin)) -> List[Dict[str, Any]]:
    return list_admin_invites()


@app.patch(
    "/admin/traceability/{trace_id}",
    tags=["Administração"],
    summary="Marcar uma entrada da matriz como revista (admin/reviewer).",
    description=(
        "Permite a um admin ou especialista atualizar o resultado, severidade, "
        "tipo de erro e notas de qualquer entrada — independentemente de quem "
        "a criou. As notas ficam prefixadas com [reviewer:<id>] para mantermos "
        "pista de quem reviu."
    ),
    operation_id="patch_admin_traceability",
)
def admin_traceability_update(
    trace_id: str,
    payload: TraceabilityReviewRequest,
    user: AuthUser = Depends(require_admin),
) -> Dict[str, Any]:
    try:
        return update_traceability_review_admin(
            trace_id=trace_id,
            reviewer_id=user.id,
            result=payload.result,
            error_type=payload.error_type,
            severity=payload.severity,
            reviewer_notes=payload.reviewer_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a atualizar matriz: {exc}",
        )


@app.patch(
    "/specialist/traceability/{trace_id}",
    tags=["Autenticação"],
    summary="Marcar uma entrada da matriz como revista (especialista).",
    description=(
        "Mesmo workflow que o endpoint admin, mas restrito a especialistas "
        "ativos. Reaproveita a mesma função de update."
    ),
    operation_id="patch_specialist_traceability",
)
def specialist_traceability_update(
    trace_id: str,
    payload: TraceabilityReviewRequest,
    user: AuthUser = Depends(require_specialist_self),
) -> Dict[str, Any]:
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas especialistas ativos podem rever a matriz.",
        )
    try:
        return update_traceability_review_admin(
            trace_id=trace_id,
            reviewer_id=user.id,
            result=payload.result,
            error_type=payload.error_type,
            severity=payload.severity,
            reviewer_notes=payload.reviewer_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a atualizar matriz: {exc}",
        )


@app.get(
    "/specialist/traceability",
    dependencies=[Depends(require_specialist_self)],
    tags=["Autenticação"],
    summary="Listagem global da matriz para especialistas (mesmos filtros do admin).",
    operation_id="get_specialist_traceability",
)
def specialist_traceability(
    limit: int = Query(200, ge=1, le=1000),
    trace_type: Optional[str] = Query(default=None, pattern="^(chat|regulatory_analysis|regulatory_document)$"),
    result: Optional[str] = Query(default=None, pattern="^(OK|PARCIAL|NOK)$"),
    severity: Optional[str] = Query(default=None, pattern="^(baixa|média|alta)$"),
    error_type: Optional[str] = Query(default=None, pattern="^E[1-7]$"),
    only_pending: bool = Query(default=False),
    user: AuthUser = Depends(require_specialist_self),
) -> List[Dict[str, Any]]:
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conta de especialista ainda não está ativa.",
        )
    try:
        return list_all_traceability_entries(
            limit=limit,
            trace_type=trace_type,
            result=result,
            severity=severity,
            error_type=error_type,
            only_pending=only_pending,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar matriz: {exc}",
        )


@app.get(
    "/admin/traceability",
    dependencies=[Depends(require_admin)],
    tags=["Administração"],
    summary="Listagem global da matriz de rastreabilidade (sem filtro de user).",
    operation_id="get_admin_traceability",
)
def admin_traceability(
    limit: int = Query(200, ge=1, le=1000),
    trace_type: Optional[str] = Query(default=None, pattern="^(chat|regulatory_analysis|regulatory_document)$"),
    result: Optional[str] = Query(default=None, pattern="^(OK|PARCIAL|NOK)$"),
    severity: Optional[str] = Query(default=None, pattern="^(baixa|média|alta)$"),
    error_type: Optional[str] = Query(default=None, pattern="^E[1-7]$"),
    only_pending: bool = Query(default=False, description="Se True, devolve só entradas com result IS NULL"),
) -> List[Dict[str, Any]]:
    try:
        return list_all_traceability_entries(
            limit=limit,
            trace_type=trace_type,
            result=result,
            severity=severity,
            error_type=error_type,
            only_pending=only_pending,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar matriz: {exc}",
        )


# ===========================================================================
# Métricas resumidas por role (alimentam as dashboards)
# ===========================================================================
from api_db import db_cursor as _metrics_cursor


def _safe_count(cur, sql: str, *params) -> int:
    try:
        cur.execute(sql, *params)
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


@app.get(
    "/admin/metrics/summary",
    dependencies=[Depends(require_admin)],
    tags=["Administração"],
    summary="KPIs agregados para a dashboard do admin.",
    operation_id="get_admin_metrics_summary",
)
def admin_metrics_summary() -> Dict[str, Any]:
    with _metrics_cursor() as cur:
        total_users = _safe_count(cur, "SELECT COUNT(*) FROM dbo.auth_users")
        active_users = _safe_count(cur, "SELECT COUNT(*) FROM dbo.auth_users WHERE role='user' AND status='active'")
        specialists_active = _safe_count(cur, "SELECT COUNT(*) FROM dbo.auth_users WHERE role='specialist' AND status='active'")
        specialists_pending = _safe_count(cur, "SELECT COUNT(*) FROM dbo.auth_users WHERE role='specialist' AND status='pending'")
        admins_total = _safe_count(cur, "SELECT COUNT(*) FROM dbo.auth_users WHERE role='admin'")
        chats_today = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE trace_type='chat' AND CAST(created_at AS DATE)=CAST(SYSUTCDATETIME() AS DATE)",
        )
        docs_generated = _safe_count(cur, "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE trace_type='regulatory_document'")
        matrix_pending_review = _safe_count(cur, "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE result IS NULL")

    # Profiles do Copilot (podem não existir se Phase 3 não correu DDL)
    profiles_total = 0
    instances_in_progress = 0
    try:
        with _metrics_cursor() as cur:
            profiles_total = _safe_count(cur, "SELECT COUNT(*) FROM dbo.product_profiles")
            instances_in_progress = _safe_count(
                cur,
                "SELECT COUNT(*) FROM dbo.document_instances WHERE state IN ('draft','partial','awaiting')",
            )
    except Exception:
        pass

    return {
        "users": {"total": total_users, "active": active_users},
        "specialists": {"active": specialists_active, "pending": specialists_pending},
        "admins": {"total": admins_total},
        "activity": {
            "chats_today": chats_today,
            "documents_generated_total": docs_generated,
            "matrix_pending_review": matrix_pending_review,
        },
        "copilot": {
            "product_profiles": profiles_total,
            "documents_in_progress": instances_in_progress,
        },
    }


@app.get(
    "/specialist/metrics/summary",
    dependencies=[Depends(require_specialist_self)],
    tags=["Autenticação"],
    summary="KPIs agregados para a dashboard do especialista.",
    operation_id="get_specialist_metrics_summary",
)
def specialist_metrics_summary(user: AuthUser = Depends(require_specialist_self)) -> Dict[str, Any]:
    # O especialista é identificado nas notas via prefix [reviewer:<id[:8]>]
    # que `update_traceability_review_admin()` adiciona quando ele faz revisão.
    # NÃO podemos filtrar por user_id (que é quem CRIOU a entrada, não quem
    # reviu).
    reviewer_tag = f"%[reviewer:{user.id[:8]}]%"

    with _metrics_cursor() as cur:
        # Pendentes para rever (globais — qualquer reviewer)
        pending = _safe_count(cur, "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE result IS NULL")
        my_reviews_total = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE result IS NOT NULL AND reviewer_notes LIKE ?",
            reviewer_tag,
        )
        my_reviews_today = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE result IS NOT NULL AND reviewer_notes LIKE ? AND CAST(updated_at AS DATE)=CAST(SYSUTCDATETIME() AS DATE)",
            reviewer_tag,
        )
        approved_ratio_num = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE result='OK' AND reviewer_notes LIKE ?",
            reviewer_tag,
        )

    approval_pct = int(round((approved_ratio_num / my_reviews_total) * 100)) if my_reviews_total else None

    return {
        "queue": {"pending_review": pending},
        "personal": {
            "reviews_total": my_reviews_total,
            "reviews_today": my_reviews_today,
            "approval_rate_pct": approval_pct,
        },
    }


@app.get(
    "/user/metrics/summary",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Autenticação"],
    summary="KPIs agregados para a dashboard do utilizador.",
    operation_id="get_user_metrics_summary",
)
def user_metrics_summary(user: AuthUser = Depends(require_chatbot_access)) -> Dict[str, Any]:
    with _metrics_cursor() as cur:
        my_chats = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE trace_type='chat' AND user_id = ?",
            user.id,
        )
        my_docs = _safe_count(
            cur,
            "SELECT COUNT(*) FROM dbo.traceability_matrix WHERE trace_type='regulatory_document' AND user_id = ?",
            user.id,
        )

    my_profiles = 0
    my_instances_active = 0
    my_instances_done = 0
    try:
        with _metrics_cursor() as cur:
            my_profiles = _safe_count(
                cur,
                "SELECT COUNT(*) FROM dbo.product_profiles WHERE user_id = ?",
                user.id,
            )
            my_instances_active = _safe_count(
                cur,
                """
                SELECT COUNT(*) FROM dbo.document_instances di
                JOIN dbo.product_profiles pp ON pp.id = di.product_profile_id
                WHERE pp.user_id = ? AND di.state IN ('draft','partial','awaiting')
                """,
                user.id,
            )
            my_instances_done = _safe_count(
                cur,
                """
                SELECT COUNT(*) FROM dbo.document_instances di
                JOIN dbo.product_profiles pp ON pp.id = di.product_profile_id
                WHERE pp.user_id = ? AND di.state IN ('reviewed','approved','exported')
                """,
                user.id,
            )
    except Exception:
        pass

    return {
        "activity": {
            "my_chat_messages": my_chats,
            "my_documents_generated": my_docs,
        },
        "copilot": {
            "my_product_profiles": my_profiles,
            "my_documents_in_progress": my_instances_active,
            "my_documents_completed": my_instances_done,
        },
    }


# ===========================================================================
# Templates regulatórios (Regulatory Documentation Copilot)
# ===========================================================================
class TemplateRecordModel(BaseModel):
    id: str
    name: str
    file: str
    category: str
    doc_type: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    regulations: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    mandatory_sections: List[str] = Field(default_factory=list)
    optional_sections: List[str] = Field(default_factory=list)
    auto_fillable_fields: List[str] = Field(default_factory=list)
    human_required_fields: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    feeds_into: List[str] = Field(default_factory=list)
    workflow_priority: int = 99
    metadata_status: str = "seed"


class TemplateSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Frase livre — contexto da conversa ou pergunta do utilizador.")
    n_results: int = Field(5, ge=1, le=20)
    category: Optional[str] = Field(default=None, description="Filtra por categoria exata.")
    regulation: Optional[str] = Field(default=None, description="Filtra por tag de regulamento (ex: MDR, AI_Act).")
    theme: Optional[str] = Field(default=None, description="Filtra por tema (ex: clinical, software, risk).")

    @field_validator("query")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A query não pode estar vazia.")
        return cleaned


class TemplateSearchHit(BaseModel):
    template: TemplateRecordModel
    score: Optional[float] = Field(default=None, description="Score [0,1]: maior = mais relevante.")
    distance: Optional[float] = None
    rationale_meta: Optional[Dict[str, Any]] = None


_TEMPLATE_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.get(
    "/templates",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[TemplateRecordModel],
    tags=["Templates"],
    summary="Listar templates regulatórios disponíveis.",
    description=(
        "Devolve o catálogo completo de templates do Regulatory Documentation "
        "Copilot. Suporta filtros opcionais por categoria, regulamento, tema e "
        "tipo de documento (TMP/FRM/SOP/LST)."
    ),
    operation_id="get_templates_list",
)
def templates_list(
    category: Optional[str] = Query(default=None),
    regulation: Optional[str] = Query(default=None),
    theme: Optional[str] = Query(default=None),
    doc_type: Optional[str] = Query(default=None, pattern="^(TMP|FRM|SOP|LST)$"),
) -> List[TemplateRecordModel]:
    try:
        records = list_templates(
            category=category,
            regulation=regulation,
            theme=theme,
            doc_type=doc_type,
        )
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return [TemplateRecordModel(**r) for r in records]


@app.get(
    "/templates/categories",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Templates"],
    summary="Listar categorias e contagem de templates por categoria.",
    operation_id="get_templates_categories",
)
def templates_categories() -> List[Dict[str, Any]]:
    try:
        return list_categories()
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    "/templates/tags",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Templates"],
    summary="Obter taxonomia de tags (regulamentos, temas, doc types).",
    operation_id="get_templates_tags",
)
def templates_tags() -> Dict[str, Any]:
    try:
        return list_tags()
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.get(
    "/templates/registry-info",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Templates"],
    summary="Metadata global do registry (versão, notas, estado da indexação).",
    operation_id="get_templates_registry_info",
)
def templates_registry_info() -> Dict[str, Any]:
    try:
        meta = get_registry_meta()
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return {**meta, "indexed": is_indexed()}


@app.get(
    "/templates/{template_id}",
    dependencies=[Depends(require_chatbot_access)],
    response_model=TemplateRecordModel,
    tags=["Templates"],
    summary="Obter metadata completa de um template.",
    operation_id="get_template_by_id",
)
def template_get(template_id: str = FPath(..., description="ID do template (ex: TMP-CE-01).")) -> TemplateRecordModel:
    try:
        record = get_record(template_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template '{template_id}' não existe.")
    return TemplateRecordModel(**record.to_dict())


@app.get(
    "/templates/{template_id}/download",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Templates"],
    summary="Descarregar o ficheiro físico do template.",
    operation_id="get_template_download",
)
def template_download(template_id: str = FPath(...)):
    try:
        path = get_template_file_path(template_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template '{template_id}' não existe.")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    media_type = _TEMPLATE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path=str(path), media_type=media_type, filename=path.name)


@app.post(
    "/templates/search",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[TemplateSearchHit],
    tags=["Templates"],
    summary="Pesquisa semântica de templates a partir de uma frase livre.",
    description=(
        "Usa embeddings sobre a metadata dos templates (nome, descrição, keywords, "
        "categoria, temas, regulamentos) para devolver os templates mais relevantes "
        "para um contexto de conversa. É a base do Document Orchestrator."
    ),
    operation_id="post_templates_search",
)
def templates_search(payload: TemplateSearchRequest) -> List[TemplateSearchHit]:
    try:
        hits = search_templates(
            query=payload.query,
            n_results=payload.n_results,
            category=payload.category,
            regulation=payload.regulation,
            theme=payload.theme,
        )
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro na pesquisa de templates: {exc}",
        )
    return [TemplateSearchHit(**hit) for hit in hits]


@app.post(
    "/admin/templates/reindex",
    tags=["Templates"],
    summary="Reindexar templates no ChromaDB (admin).",
    description="Recria a collection `bridgemedai_templates` a partir do registry.json. Use após editar metadata.",
    operation_id="post_admin_templates_reindex",
)
def admin_templates_reindex(
    rebuild: bool = Query(default=True, description="Se True, apaga a collection antes de re-embeber."),
    _: AuthUser = Depends(require_admin),
) -> Dict[str, Any]:
    try:
        reload_registry()
        return index_templates(rebuild=rebuild)
    except RegistryError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a reindexar templates: {exc}",
        )


# ===========================================================================
# Document Orchestrator — sugestões contextuais (Copilot)
# ===========================================================================
class SuggestionRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="Mensagem atual do utilizador (mesma que vai para /chat).",
    )
    history: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Últimas mensagens da conversa, mesmo formato do /chat.",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="Identificador da conversa no frontend (para rastreabilidade futura).",
    )
    n_results: int = Field(5, ge=1, le=15)
    category: Optional[str] = Field(default=None, description="Filtra por categoria.")
    regulation: Optional[str] = Field(default=None, description="Filtra por tag de regulamento (ex: MDR, AI_Act).")
    theme: Optional[str] = Field(default=None, description="Filtra por tema (ex: clinical, software, risk).")

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A pergunta não pode estar vazia.")
        return cleaned


class TemplatePrerequisite(BaseModel):
    id: str
    name: str
    category: str


class TemplateSuggestion(BaseModel):
    template: TemplateRecordModel
    score: Optional[float] = Field(default=None, description="Score [0,1] do retrieval semântico.")
    matched_regulations: List[str] = Field(
        default_factory=list,
        description="Regulamentos do template mencionados explicitamente na conversa.",
    )
    matched_themes: List[str] = Field(
        default_factory=list,
        description="Temas do template mencionados explicitamente na conversa.",
    )
    prerequisites: List[TemplatePrerequisite] = Field(
        default_factory=list,
        description="Documentos dos quais este template depende (dependencies).",
    )
    rationale: str = Field(
        ...,
        description="Frase legível a explicar porque o template foi sugerido.",
    )


class SuggestionResponse(BaseModel):
    context_query: str = Field(
        ...,
        description="Texto efetivamente usado para a pesquisa semântica.",
    )
    detected_regulations: List[str] = Field(
        default_factory=list,
        description="Regulamentos detetados explicitamente na conversa.",
    )
    detected_themes: List[str] = Field(
        default_factory=list,
        description="Temas regulatórios detetados explicitamente na conversa.",
    )
    suggestions: List[TemplateSuggestion]


@app.post(
    "/chat/suggestions",
    dependencies=[Depends(require_chatbot_access)],
    response_model=SuggestionResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    tags=["Copilot"],
    summary="Sugestões contextuais de templates para a conversa atual",
    description=(
        "Recebe a pergunta atual e o histórico recente do chat e devolve até N "
        "templates relevantes, com score semântico, regulamentos e temas "
        "explicitamente discutidos, e rationale legível.\n\n"
        "Pensado para ser chamado em paralelo com `/chat` pelo frontend, sem "
        "interferir com o fluxo conversacional/regulatório existente. Se a "
        "collection ChromaDB de templates ainda não estiver indexada, é criada "
        "automaticamente no primeiro pedido."
    ),
    operation_id="post_chat_suggestions",
)
def chat_suggestions(payload: SuggestionRequest) -> SuggestionResponse:
    try:
        result = suggest_templates(
            question=payload.question,
            history=payload.history or [],
            n_results=payload.n_results,
            category=payload.category,
            regulation=payload.regulation,
            theme=payload.theme,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar sugestões: {exc}",
        )

    return SuggestionResponse(
        context_query=result["context_query"],
        detected_regulations=result["detected_regulations"],
        detected_themes=result["detected_themes"],
        suggestions=[TemplateSuggestion(**s) for s in result["suggestions"]],
    )


@app.get(
    "/chat/suggestions/taxonomy",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Copilot"],
    summary="Taxonomia conhecida pelo orchestrator (regulamentos, temas, aliases).",
    operation_id="get_chat_suggestions_taxonomy",
)
def chat_suggestions_taxonomy() -> Dict[str, Any]:
    return orchestrator_taxonomy()


# ===========================================================================
# Context Memory — perfis de produto, campos extraídos, documentos, estado
# ===========================================================================
class ProductProfileModel(BaseModel):
    id: str
    user_id: str
    conversation_id: Optional[str] = None
    name: Optional[str] = None
    mdr_class: Optional[str] = Field(default=None, pattern="^(I|IIa|IIb|III)$")
    ai_system_flag: Optional[bool] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProductProfileCreateRequest(BaseModel):
    name: Optional[str] = None
    conversation_id: Optional[str] = None
    mdr_class: Optional[str] = Field(default=None, pattern="^(I|IIa|IIb|III)$")
    ai_system_flag: Optional[bool] = None
    summary: Optional[str] = None


class ProductProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    mdr_class: Optional[str] = Field(default=None, pattern="^(I|IIa|IIb|III)$")
    ai_system_flag: Optional[bool] = None
    summary: Optional[str] = None


class ExtractedFieldModel(BaseModel):
    id: str
    product_profile_id: str
    field_key: str
    field_value: Optional[str] = None
    source: str
    confidence: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FieldSetRequest(BaseModel):
    field_value: Optional[str] = None
    source: str = Field(default="manual", pattern="^(conversation|manual|document|analysis|llm)$")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class DocumentInstanceModel(BaseModel):
    id: str
    product_profile_id: str
    template_id: str
    state: str
    file_path: Optional[str] = None
    download_name: Optional[str] = None
    notes: Optional[str] = None
    last_review_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DocumentInstanceCreateRequest(BaseModel):
    template_id: str = Field(..., min_length=1)
    state: str = Field(default="draft", pattern="^(draft|partial|awaiting|reviewed|approved|exported)$")
    notes: Optional[str] = None


class DocumentInstanceUpdateRequest(BaseModel):
    state: Optional[str] = Field(default=None, pattern="^(draft|partial|awaiting|reviewed|approved|exported)$")
    file_path: Optional[str] = None
    download_name: Optional[str] = None
    notes: Optional[str] = None
    mark_reviewed: bool = False


class DocumentationStateModel(BaseModel):
    product_profile_id: str
    missing_information: List[Dict[str, Any]] = Field(default_factory=list)
    pending_sections: Dict[str, Any] = Field(default_factory=dict)
    progress_percent: Optional[int] = None
    notes: Optional[str] = None
    updated_at: Optional[str] = None


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Excerto de conversa de onde extrair informação.")
    field_keys: Optional[List[str]] = Field(
        default=None,
        description="Lista de chaves canónicas a extrair. Omitir para usar o set por defeito.",
    )
    persist: bool = Field(
        default=False,
        description="Se True, persiste os campos extraídos com source='llm'. Caso contrário só devolve.",
    )

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Texto não pode estar vazio.")
        return cleaned


class ExtractResponse(BaseModel):
    extracted: Dict[str, Optional[str]] = Field(
        ...,
        description="Campos extraídos pelo LLM. `null` significa que não havia informação.",
    )
    persisted_keys: List[str] = Field(
        default_factory=list,
        description="Chaves que foram efetivamente persistidas em extracted_fields.",
    )


# ---- Profiles -------------------------------------------------------------

@app.get(
    "/memory/profiles",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[ProductProfileModel],
    tags=["Memória"],
    summary="Listar perfis de produto do utilizador.",
    operation_id="get_memory_profiles",
)
def memory_list_profiles(
    limit: int = Query(50, ge=1, le=200),
    user: AuthUser = Depends(require_chatbot_access),
) -> List[ProductProfileModel]:
    try:
        return [ProductProfileModel(**p) for p in cm_list_profiles(user_id=user.id, limit=limit)]
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro a listar perfis: {exc}")


@app.post(
    "/memory/profiles",
    dependencies=[Depends(require_chatbot_access)],
    response_model=ProductProfileModel,
    status_code=status.HTTP_201_CREATED,
    tags=["Memória"],
    summary="Criar (ou obter) perfil de produto para a conversa atual.",
    description=(
        "Se `conversation_id` for fornecido e já existir um perfil para essa conversa, "
        "devolve-o; caso contrário cria um novo. Sem `conversation_id` cria sempre novo."
    ),
    operation_id="post_memory_profile_create",
)
def memory_create_profile(
    payload: ProductProfileCreateRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> ProductProfileModel:
    try:
        if payload.conversation_id:
            profile = get_or_create_profile_for_conversation(
                user_id=user.id,
                conversation_id=payload.conversation_id,
            )
            # Aplica overrides opcionais à entrada existente/nova
            if any(v is not None for v in (payload.name, payload.mdr_class, payload.ai_system_flag, payload.summary)):
                profile = update_profile_core(
                    profile_id=profile["id"],
                    user_id=user.id,
                    name=payload.name,
                    mdr_class=payload.mdr_class,
                    ai_system_flag=payload.ai_system_flag,
                    summary=payload.summary,
                )
            return ProductProfileModel(**profile)

        profile = cm_create_profile(
            user_id=user.id,
            conversation_id=payload.conversation_id,
            name=payload.name,
            mdr_class=payload.mdr_class,
            ai_system_flag=payload.ai_system_flag,
            summary=payload.summary,
        )
        return ProductProfileModel(**profile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro a criar perfil: {exc}")


@app.get(
    "/memory/profiles/{profile_id}",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Memória"],
    summary="Snapshot completo do perfil (core + fields + documentos + estado).",
    operation_id="get_memory_profile_snapshot",
)
def memory_get_profile(
    profile_id: str = FPath(...),
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return get_profile_snapshot(profile_id=profile_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.patch(
    "/memory/profiles/{profile_id}",
    dependencies=[Depends(require_chatbot_access)],
    response_model=ProductProfileModel,
    tags=["Memória"],
    summary="Atualizar campos core do perfil.",
    operation_id="patch_memory_profile",
)
def memory_update_profile(
    profile_id: str,
    payload: ProductProfileUpdateRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> ProductProfileModel:
    try:
        return ProductProfileModel(
            **update_profile_core(
                profile_id=profile_id,
                user_id=user.id,
                name=payload.name,
                mdr_class=payload.mdr_class,
                ai_system_flag=payload.ai_system_flag,
                summary=payload.summary,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.delete(
    "/memory/profiles/{profile_id}",
    dependencies=[Depends(require_chatbot_access)],
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Memória"],
    summary="Apagar perfil e tudo o que está associado (CASCADE).",
    operation_id="delete_memory_profile",
)
def memory_delete_profile(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> None:
    try:
        cm_delete_profile(profile_id=profile_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---- Fields ---------------------------------------------------------------

@app.get(
    "/memory/profiles/{profile_id}/fields",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[ExtractedFieldModel],
    tags=["Memória"],
    summary="Listar todos os campos extraídos de um perfil.",
    operation_id="get_memory_profile_fields",
)
def memory_list_fields(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> List[ExtractedFieldModel]:
    try:
        return [ExtractedFieldModel(**f) for f in cm_list_fields(profile_id=profile_id, user_id=user.id)]
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.put(
    "/memory/profiles/{profile_id}/fields/{field_key}",
    dependencies=[Depends(require_chatbot_access)],
    response_model=ExtractedFieldModel,
    tags=["Memória"],
    summary="Definir ou atualizar um campo extraído (upsert).",
    operation_id="put_memory_profile_field",
)
def memory_set_field(
    profile_id: str,
    field_key: str,
    payload: FieldSetRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> ExtractedFieldModel:
    try:
        return ExtractedFieldModel(
            **cm_set_field(
                profile_id=profile_id,
                user_id=user.id,
                field_key=field_key,
                field_value=payload.field_value,
                source=payload.source,
                confidence=payload.confidence,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.delete(
    "/memory/profiles/{profile_id}/fields/{field_key}",
    dependencies=[Depends(require_chatbot_access)],
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Memória"],
    summary="Apagar um campo extraído.",
    operation_id="delete_memory_profile_field",
)
def memory_delete_field(
    profile_id: str,
    field_key: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> None:
    try:
        cm_delete_field(profile_id=profile_id, user_id=user.id, field_key=field_key)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.get(
    "/memory/fields/catalog",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Memória"],
    summary="Listar campos canónicos derivados do registry e onde são usados.",
    operation_id="get_memory_fields_catalog",
)
def memory_fields_catalog() -> Dict[str, Any]:
    keys = canonical_field_keys()
    return {
        "field_keys": keys,
        "usage": {k: templates_using_field(k) for k in keys},
    }


# ---- Document instances ---------------------------------------------------

@app.post(
    "/memory/profiles/{profile_id}/documents",
    dependencies=[Depends(require_chatbot_access)],
    response_model=DocumentInstanceModel,
    status_code=status.HTTP_201_CREATED,
    tags=["Memória"],
    summary="Iniciar uma instância de documento para o perfil.",
    operation_id="post_memory_profile_document",
)
def memory_create_instance(
    profile_id: str,
    payload: DocumentInstanceCreateRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> DocumentInstanceModel:
    try:
        # valida que o template existe no registry
        get_record(payload.template_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template '{payload.template_id}' não existe.")

    try:
        return DocumentInstanceModel(
            **cm_create_instance(
                profile_id=profile_id,
                user_id=user.id,
                template_id=payload.template_id,
                state=payload.state,
                notes=payload.notes,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.get(
    "/memory/profiles/{profile_id}/documents",
    dependencies=[Depends(require_chatbot_access)],
    response_model=List[DocumentInstanceModel],
    tags=["Memória"],
    summary="Listar instâncias de documentos de um perfil.",
    operation_id="get_memory_profile_documents",
)
def memory_list_instances(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> List[DocumentInstanceModel]:
    try:
        return [DocumentInstanceModel(**d) for d in cm_list_instances(profile_id=profile_id, user_id=user.id)]
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.patch(
    "/memory/documents/{instance_id}",
    dependencies=[Depends(require_chatbot_access)],
    response_model=DocumentInstanceModel,
    tags=["Memória"],
    summary="Atualizar estado/notas/ficheiro de uma instância.",
    operation_id="patch_memory_document",
)
def memory_update_instance(
    instance_id: str,
    payload: DocumentInstanceUpdateRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> DocumentInstanceModel:
    try:
        return DocumentInstanceModel(
            **cm_update_instance(
                instance_id=instance_id,
                user_id=user.id,
                state=payload.state,
                file_path=payload.file_path,
                download_name=payload.download_name,
                notes=payload.notes,
                mark_reviewed=payload.mark_reviewed,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.delete(
    "/memory/documents/{instance_id}",
    dependencies=[Depends(require_chatbot_access)],
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Memória"],
    summary="Apagar instância de documento.",
    operation_id="delete_memory_document",
)
def memory_delete_instance(
    instance_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> None:
    try:
        cm_delete_instance(instance_id=instance_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---- Documentation state + extraction -------------------------------------

@app.post(
    "/memory/profiles/{profile_id}/state/recompute",
    dependencies=[Depends(require_chatbot_access)],
    response_model=DocumentationStateModel,
    tags=["Memória"],
    summary="Recalcular o snapshot de estado documental a partir do registry + fields atuais.",
    operation_id="post_memory_recompute_state",
)
def memory_recompute_state(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> DocumentationStateModel:
    try:
        return DocumentationStateModel(**recompute_documentation_state(profile_id=profile_id, user_id=user.id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@app.post(
    "/memory/profiles/{profile_id}/extract",
    dependencies=[Depends(require_chatbot_access)],
    response_model=ExtractResponse,
    tags=["Memória"],
    summary="Extrair campos canónicos de um excerto de conversa (opt-in LLM).",
    description=(
        "Usa o LLM (Ollama, modelo `OLLAMA_CHAT_MODEL`) para inferir campos canónicos a "
        "partir de um excerto. Por defeito não persiste; passar `persist=true` para gravar "
        "os campos não-nulos em `extracted_fields` com source='llm'."
    ),
    operation_id="post_memory_extract_fields",
)
def memory_extract_fields(
    profile_id: str,
    payload: ExtractRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> ExtractResponse:
    # valida ownership do profile primeiro
    try:
        cm_get_profile(profile_id=profile_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    try:
        extracted = extract_fields_from_text(payload.text, field_keys=payload.field_keys)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha do extrator LLM: {exc}",
        )

    persisted: List[str] = []
    if payload.persist:
        for key, value in extracted.items():
            if not value:
                continue
            try:
                cm_set_field(
                    profile_id=profile_id,
                    user_id=user.id,
                    field_key=key,
                    field_value=value,
                    source="llm",
                )
                persisted.append(key)
            except Exception:
                continue

    return ExtractResponse(extracted=extracted, persisted_keys=persisted)


# ===========================================================================
# Auto-fill Engine — geração de .docx pré-preenchido a partir do Context Memory
# ===========================================================================
class CoverageModel(BaseModel):
    total: int
    filled: int
    coverage_pct: int
    missing: List[str] = Field(default_factory=list)
    missing_human_required: List[str] = Field(default_factory=list)
    missing_auto_fillable: List[str] = Field(default_factory=list)


class AutofillResult(BaseModel):
    instance: DocumentInstanceModel
    template: Dict[str, Any]
    coverage: CoverageModel
    replacement_report: Dict[str, Any]
    previous_state: str
    new_state: str


@app.post(
    "/memory/documents/{instance_id}/autofill",
    dependencies=[Depends(require_chatbot_access)],
    response_model=AutofillResult,
    tags=["Memória"],
    summary="Gerar .docx pré-preenchido para uma instância de documento.",
    description=(
        "Cruza os `extracted_fields` do perfil com os `auto_fillable_fields`/"
        "`human_required_fields` do template. Substitui placeholders `{{field_key}}` "
        "no corpo do .docx e insere um cover sheet com o contexto conhecido. "
        "Atualiza o estado da instância para `partial`/`awaiting` conforme a cobertura."
    ),
    operation_id="post_memory_document_autofill",
)
def memory_document_autofill(
    instance_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> AutofillResult:
    try:
        result = autofill_instance(instance_id=instance_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except AutofillError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no auto-fill: {exc}",
        )
    return AutofillResult(
        instance=DocumentInstanceModel(**result["instance"]),
        template=result["template"],
        coverage=CoverageModel(**result["coverage"]),
        replacement_report=result["replacement_report"],
        previous_state=result["previous_state"],
        new_state=result["new_state"],
    )


@app.get(
    "/memory/documents/{instance_id}/download",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Memória"],
    summary="Descarregar o .docx gerado pela última execução de auto-fill.",
    operation_id="get_memory_document_download",
)
def memory_document_download(
    instance_id: str,
    user: AuthUser = Depends(require_chatbot_access),
):
    try:
        path = get_generated_file_path(instance_id=instance_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


@app.post(
    "/memory/profiles/{profile_id}/autofill-all",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Memória"],
    summary="Auto-fill em bulk para todas as instâncias de um perfil.",
    description="Itera todas as document_instances do perfil. Retorna lista mista (ok/erro por instância).",
    operation_id="post_memory_profile_autofill_all",
)
def memory_profile_autofill_all(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> List[Dict[str, Any]]:
    try:
        return autofill_all_for_profile(profile_id=profile_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no bulk auto-fill: {exc}",
        )


# ===========================================================================
# Workflow Engine — dependências entre templates + paths recomendados
# ===========================================================================
class WorkflowApplyRequest(BaseModel):
    template_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Lista explícita de template_ids a criar. Se omisso, usa a recomendação "
            "automática do perfil."
        ),
    )


@app.get(
    "/templates/{template_id}/dependencies",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Workflow"],
    summary="Grafo de dependências e downstream de um template.",
    description=(
        "Devolve para o template:\n"
        "- `direct_dependencies` / `direct_feeds_into` (1 hop, do registry)\n"
        "- `transitive_dependencies` (todos os pré-requisitos, em ordem topológica)\n"
        "- `transitive_downstream` (todos os documentos que dependem deste)"
    ),
    operation_id="get_template_dependencies",
)
def template_dependencies(template_id: str = FPath(...)) -> Dict[str, Any]:
    try:
        return get_template_dependency_view(template_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template '{template_id}' não existe.")


@app.get(
    "/memory/profiles/{profile_id}/workflow",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Workflow"],
    summary="Workflow recomendado + validação para o perfil atual.",
    description=(
        "Cruza o contexto do perfil (classe MDR, uso de IA, presença de software) "
        "com os blocos de workflow predefinidos e devolve a sequência completa, "
        "marcando quais templates já foram iniciados e quais faltam. Adiciona "
        "warnings sobre dependências em falta entre instâncias já iniciadas."
    ),
    operation_id="get_memory_profile_workflow",
)
def memory_profile_workflow(
    profile_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return workflow_for_profile(profile_id=profile_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a calcular workflow: {exc}",
        )


@app.post(
    "/memory/profiles/{profile_id}/workflow/apply",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Workflow"],
    summary="Criar em bulk as document_instances do workflow recomendado.",
    description=(
        "Cria automaticamente as instâncias para os templates do path recomendado "
        "que ainda não existam no perfil. Aceita também uma lista explícita de "
        "`template_ids` para aplicar um subset."
    ),
    operation_id="post_memory_profile_workflow_apply",
)
def memory_profile_workflow_apply(
    profile_id: str,
    payload: WorkflowApplyRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return apply_workflow(
            profile_id=profile_id,
            user_id=user.id,
            template_ids=payload.template_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a aplicar workflow: {exc}",
        )


# ===========================================================================
# Chat questionnaire — preenchimento conversacional turn-by-turn
# ===========================================================================
class QuestionnaireStartRequest(BaseModel):
    conversation_id: Optional[str] = Field(default=None, description="ID da conversa do frontend.")
    template_ids: List[str] = Field(..., min_length=1, description="Templates a preencher juntos.")


class QuestionnaireAnswerRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    answer: str = Field(..., description="Resposta do utilizador à pergunta atual; vazio ou 'skip' para saltar.")


@app.post(
    "/chat/questionnaire/start",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Copilot"],
    summary="Iniciar preenchimento conversacional de um ou mais templates.",
    description=(
        "Cria uma sessão de questionário em memória. Calcula a fila de campos "
        "necessários (auto_fillable ∪ human_required) deduplicada entre templates, "
        "salta campos já preenchidos no perfil, e devolve a próxima pergunta. "
        "Se já estiver tudo preenchido, dispara o auto-fill imediatamente."
    ),
    operation_id="post_chat_questionnaire_start",
)
def chat_questionnaire_start(
    payload: QuestionnaireStartRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return start_questionnaire(
            user_id=user.id,
            conversation_id=payload.conversation_id,
            template_ids=payload.template_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a iniciar questionário: {exc}",
        )


@app.post(
    "/chat/questionnaire/answer",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Copilot"],
    summary="Responder à pergunta atual; devolve a próxima ou completa o fluxo.",
    operation_id="post_chat_questionnaire_answer",
)
def chat_questionnaire_answer(
    payload: QuestionnaireAnswerRequest,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return answer_current_question(
            session_id=payload.session_id,
            user_id=user.id,
            answer_text=payload.answer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro a processar resposta: {exc}",
        )


@app.get(
    "/chat/questionnaire/{session_id}",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Copilot"],
    summary="Estado atual de uma sessão de questionário.",
    operation_id="get_chat_questionnaire_state",
)
def chat_questionnaire_get_state(
    session_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return questionnaire_state(session_id=session_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@app.delete(
    "/chat/questionnaire/{session_id}",
    dependencies=[Depends(require_chatbot_access)],
    tags=["Copilot"],
    summary="Cancelar uma sessão de questionário.",
    operation_id="delete_chat_questionnaire",
)
def chat_questionnaire_delete(
    session_id: str,
    user: AuthUser = Depends(require_chatbot_access),
) -> Dict[str, Any]:
    try:
        return questionnaire_cancel(session_id=session_id, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))