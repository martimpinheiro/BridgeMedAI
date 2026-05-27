from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

CHROMA_MODE = os.getenv("CHROMA_MODE", "http").strip().lower()
CHROMA_HOST = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8002"))
CHROMA_SSL = os.getenv("CHROMA_SSL", "false").strip().lower() == "true"

CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()

CHROMA_COLLECTION_NAME = os.getenv(
    "CHROMA_COLLECTION_NAME",
    "regulations_chunks",
)

USER_DOCS_CHROMA_COLLECTION_NAME = os.getenv(
    "USER_DOCS_CHROMA_COLLECTION_NAME",
    "user_documents_chunks",
)


def get_chroma_client():
    if CHROMA_MODE == "http":
        return chromadb.HttpClient(
            host=CHROMA_HOST,
            port=CHROMA_PORT,
            ssl=CHROMA_SSL,
            settings=Settings(anonymized_telemetry=False),
        )

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(CHROMA_PERSIST_DIR),
        settings=Settings(anonymized_telemetry=False),
    )


def get_chroma_collection(name: Optional[str] = None):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name or CHROMA_COLLECTION_NAME)


def get_user_documents_collection():
    return get_chroma_collection(USER_DOCS_CHROMA_COLLECTION_NAME)


def chroma_has_documents() -> bool:
    collection = get_chroma_collection()
    return collection.count() > 0


def user_documents_chroma_has_documents() -> bool:
    collection = get_user_documents_collection()
    return collection.count() > 0


def chroma_peek(limit: int = 3) -> Dict[str, Any]:
    collection = get_chroma_collection()
    return collection.get(limit=limit, include=["metadatas", "documents"])


def user_documents_chroma_peek(limit: int = 3) -> Dict[str, Any]:
    collection = get_user_documents_collection()
    return collection.get(limit=limit, include=["metadatas", "documents"])


def chroma_reset_collection() -> None:
    if CHROMA_MODE == "http":
        client = get_chroma_client()
        try:
            client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
        client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)
        return

    if CHROMA_PERSIST_DIR.exists():
        shutil.rmtree(CHROMA_PERSIST_DIR, ignore_errors=True)

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(CHROMA_PERSIST_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)


def query_chroma(
    query_embedding: List[float],
    n_results: int = 12,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    collection = get_chroma_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )


def query_user_documents_chroma(
    query_embedding: List[float],
    n_results: int = 5,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    collection = get_user_documents_collection()
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )


def delete_user_document_from_chroma(
    *,
    user_id: str,
    document_id: str,
) -> None:
    collection = get_user_documents_collection()
    try:
        collection.delete(
            where={
                "$and": [
                    {"user_id": str(user_id)},
                    {"document_id": str(document_id)},
                ]
            }
        )
    except Exception:
        # Não bloquear a app se a collection ainda não existir ou se já não houver chunks.
        pass