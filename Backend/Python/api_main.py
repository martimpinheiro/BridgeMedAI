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

from typing import List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from api_rag_service import search_question, answer_question


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
class QuestionRequest(BaseModel):
    """
    Modelo de pedido usado pelos endpoints que recebem uma pergunta textual.
    """

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

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """
        Remove espaços redundantes e impede perguntas vazias após trim.
        """
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A pergunta não pode estar vazia.")
        return cleaned

    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "Que regulamentos preciso de cumprir para um dispositivo médico com IA?"
            }
        }
    }


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
        return search_question(payload.question)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante o processo de pesquisa semântica.",
        )


@app.post(
    "/chat",
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
def chat_endpoint(payload: QuestionRequest) -> ChatResponse:
    """
    Executa o fluxo completo de pergunta-resposta do BridgeMedAI.

    Este é o endpoint principal da aplicação para interação conversacional.
    A pergunta recebida é processada pela camada de serviço, que trata da
    recuperação de contexto normativo e da geração da resposta final.
    """
    try:
        return answer_question(payload.question)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno durante o processo de retrieval ou geração.",
        )