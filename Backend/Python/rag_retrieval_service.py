"""
Camada de retrieval abstrata do BridgeMedAI.

Objetivo:
- esconder a origem do retrieval (pickle ou ChromaDB);
- devolver sempre o mesmo formato para o api_rag_service;
- permitir migração gradual sem partir o pipeline atual.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from rag_router_utils import (
    validate_embeddings_payload,
    retrieve_relevant_indices,
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

RAG_BACKEND = os.getenv("RAG_BACKEND", "pickle").strip().lower()
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()

CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "regulations_chunks")
CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()


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
    """
    backend = (RAG_BACKEND or "pickle").lower()

    if backend == "chroma":
        return _retrieve_sources_chroma(question=question, history=history)

    return _retrieve_sources_pickle(question=question, history=history)


def _retrieve_sources_pickle(
    *,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Retrieval atual baseado no ficheiro local de embeddings.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
    records = payload["records"]
    embeddings = payload["embeddings"]

    selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
        question=question,
        records=records,
        embeddings=embeddings,
        embed_model=OLLAMA_EMBED_MODEL,
    )

    return {
        "backend": "pickle",
        "records": records,
        "selected_indices": selected_indices,
        "base_scores": base_scores,
        "adjusted_scores": adjusted_scores,
        "plan": plan,
    }


def _retrieve_sources_chroma(
    *,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Stub inicial para ChromaDB.

    Nesta fase 1, ainda não faz retrieval real por Chroma.
    Serve apenas para:
    - validar a configuração;
    - manter a arquitetura pronta;
    - permitir fallback seguro para pickle.
    """
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError(
            "chromadb não está instalado no ambiente atual."
        ) from exc

    if not CHROMA_PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"Diretório do Chroma não encontrado: {CHROMA_PERSIST_DIR}"
        )

    # Validação mínima da collection
    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    try:
        client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception as exc:
        raise RuntimeError(
            f"Collection Chroma '{CHROMA_COLLECTION_NAME}' não encontrada."
        ) from exc

    # Fallback temporário para o retrieval atual.
    # Na fase 2 substituímos esta parte por retrieval real via Chroma.
    result = _retrieve_sources_pickle(question=question, history=history)
    result["backend"] = "chroma-fallback-pickle"
    return result