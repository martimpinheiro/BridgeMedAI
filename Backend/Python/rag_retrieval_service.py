"""
Camada de retrieval abstrata do BridgeMedAI.

Objetivo:
- esconder a origem do retrieval;
- usar ChromaDB real quando VECTOR_STORE=chroma;
- manter fallback para pickle apenas quando Chroma não estiver configurado/disponível;
- devolver sempre o mesmo formato para debug, testes e outros serviços.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from dotenv import load_dotenv

from rag_router_utils import (
    analyze_question,
    validate_embeddings_payload,
    retrieve_relevant_indices,
)

from rag_chromadb_service import chroma_has_documents

# Importamos apenas funções de retrieval do api_rag_service,
# para garantir que este serviço usa exatamente o mesmo pipeline real do chatbot.
from api_rag_service import (
    build_contextual_question,
    is_explicit_follow_up_question,
    query_chroma_with_variants,
    select_chroma_retrieved_indices,
)


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

VECTOR_STORE = os.getenv("VECTOR_STORE", os.getenv("RAG_BACKEND", "pickle")).strip().lower()
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")

EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


HIGH_RECALL_INTENTS = {
    "manufacturer_obligations",
    "classification_risk",
    "documentation",
    "document_generation",
    "ai_provider_obligations",
    "ai_high_risk",
    "gspr_requirements",
    "conformity_procedure",
    "device_qualification",
    "clinical_evaluation_terms",
    "classification_and_scope",
    "pms_plan",
    "pmcf",
    "ai_human_oversight",
    "ai_high_risk_requirements",
    "pmcf_plan",
    "pms_pmcf_vigilance",
}


def _n_results_for_intent(intent: str) -> int:
    """
    Usa o mesmo comportamento do api_rag_service:
    intents regulatórios importantes recebem mais candidatos por query variant.
    """
    return 25 if intent in HIGH_RECALL_INTENTS else 12


def _retrieval_max_items_for_intent(intent: str) -> int:
    """
    Mantém a mesma lógica usada no api_rag_service para limitar fontes recuperadas.
    """
    if intent == "classification_risk":
        return 10

    if intent == "classification_and_scope":
        return 14

    return 18


def retrieve_sources(
    *,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Ponto único de entrada para retrieval.

    Devolve sempre:
    - records
    - selected_indices
    - base_scores
    - adjusted_scores
    - plan
    - backend

    Regra importante:
    - O plano/intenção é calculado pela pergunta atual.
    - O histórico só é usado para construir a pergunta de retrieval quando a pergunta
      atual é um follow-up explícito.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    question_clean = (question or "").strip()
    if not question_clean:
        raise ValueError("A pergunta não pode estar vazia.")

    plan = analyze_question(question_clean)

    is_follow_up = is_explicit_follow_up_question(question_clean)

    retrieval_question = (
        build_contextual_question(question_clean, history)
        if is_follow_up and history
        else question_clean
    )

    if VECTOR_STORE == "chroma" and chroma_has_documents():
        return _retrieve_sources_chroma(
            question=retrieval_question,
            plan=plan,
        )

    return _retrieve_sources_pickle(
        question=retrieval_question,
        plan=plan,
    )


def _retrieve_sources_chroma(
    *,
    question: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Retrieval real por ChromaDB.

    Usa:
    - query variants do rag_router_utils;
    - embeddings Ollama;
    - filtros por target_docs;
    - merge/deduplicação de candidatos;
    - adjusted_score com as mesmas heurísticas do pipeline principal;
    - seleção final com select_chroma_retrieved_indices.
    """
    intent = plan.get("intent", "requirement_lookup")

    n_results = _n_results_for_intent(intent)

    records, base_scores, adjusted_scores, _ = query_chroma_with_variants(
        question,
        plan,
        n_results_per_query=n_results,
    )

    if not records:
        raise ValueError("Não foi possível recuperar contexto relevante no ChromaDB.")

    selected_indices = select_chroma_retrieved_indices(
        records=records,
        adjusted_scores=adjusted_scores,
        plan=plan,
        max_items=_retrieval_max_items_for_intent(intent),
    )

    if not selected_indices:
        raise ValueError("Não foi possível selecionar fontes relevantes do ChromaDB.")

    return {
        "backend": "chroma",
        "records": records,
        "selected_indices": selected_indices,
        "base_scores": np.asarray(base_scores, dtype=float),
        "adjusted_scores": np.asarray(adjusted_scores, dtype=float),
        "plan": plan,
    }


def _retrieve_sources_pickle(
    *,
    question: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Fallback legado baseado no ficheiro local de embeddings.

    Só deve ser usado quando VECTOR_STORE não for 'chroma' ou quando a collection
    Chroma ainda não tiver documentos.
    """
    payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
    records = payload["records"]
    embeddings = payload["embeddings"]

    selected_indices, base_scores, adjusted_scores, _retrieval_plan = retrieve_relevant_indices(
        question=question,
        records=records,
        embeddings=embeddings,
        embed_model=OLLAMA_EMBED_MODEL,
    )

    if not selected_indices:
        raise ValueError("Não foi possível recuperar contexto relevante no fallback pickle.")

    return {
        "backend": "pickle",
        "records": records,
        "selected_indices": selected_indices,
        "base_scores": base_scores,
        "adjusted_scores": adjusted_scores,
        "plan": plan,
    }