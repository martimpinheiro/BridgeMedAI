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
    list_traceability_entries,
    log_chat_trace,
    log_regulatory_analysis_trace,
    log_regulatory_document_trace,
    update_traceability_review,
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
        examples=["regulatory_scope", "classification_risk"],
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
    """Acesso ao chatbot e fluxo regulatório — user ou specialist, com conta activa."""
    if user.role not in ("user", "specialist"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito a users e especialistas.")
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
    commands = [
        "faz agora o documento pmcf",
        "faz o documento pmcf",
        "gera o documento pmcf",
        "gera o pmcf",
        "cria o documento pmcf",
        "preenche o pmcf",
        "faz agora o pmcf",
    ]
    return any(cmd in t for cmd in commands)


def _looks_like_device_description(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False

    if "?" in t:
        return False

    device_signals = [
        "dispositivo médico",
        "software médico",
        "algoritmo de ia",
        "sensor de",
        "utilização em contexto clínico",
        "profissionais de saúde",
        "finalidade prevista",
        "termómetro",
        "pacemaker",
        "ressonância magnética",
        "monitorização",
        "diagnóstico",
        "classe i",
        "classe iia",
        "classe iib",
        "classe iii",
    ]

    hits = sum(1 for s in device_signals if s in t)
    return len(t) >= 80 and hits >= 2


def _resolve_regulatory_description(
    description: str,
    history: Optional[List[ConversationMessage]],
) -> str:
    cleaned = (description or "").strip()

    if cleaned and not _is_pmcf_generation_command(cleaned):
        return cleaned

    if history:
        for msg in reversed(history):
            if msg.role != "user":
                continue

            content = (msg.content or "").strip()
            if not content:
                continue

            if _is_pmcf_generation_command(content):
                continue

            if _looks_like_device_description(content):
                return content

    return cleaned

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


class TraceabilityReviewRequest(BaseModel):
    result: Optional[str] = Field(default=None, pattern="^(OK|PARCIAL|NOK)?$")
    error_type: Optional[str] = Field(default=None, pattern="^(E1|E2|E3|E4|E5|E6|E7)?$")
    severity: Optional[str] = Field(default=None, pattern="^(baixa|média|alta)?$")
    reviewer_notes: Optional[str] = None


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
    specialty: str = Form(..., min_length=2),
    institution: str = Form(..., min_length=2),
    country: str = Form(..., min_length=2),
    credentials: List[UploadFile] = File(..., description="Documentos comprovativos (.pdf, .jpg, .png)."),
) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tem de carregar pelo menos um documento.")
    try:
        user = register_specialist(email, password, full_name, specialty, institution, country)
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