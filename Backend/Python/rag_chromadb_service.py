from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_db")
).resolve()

CHROMA_COLLECTION_NAME = os.getenv(
    "CHROMA_COLLECTION_NAME",
    "bridgemedai_regulatory",
)


def get_chroma_client() -> chromadb.PersistentClient:
    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(CHROMA_PERSIST_DIR),
        settings=Settings(anonymized_telemetry=False),
    )


def get_chroma_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)


def chroma_has_documents() -> bool:
    collection = get_chroma_collection()
    return collection.count() > 0


def chroma_peek(limit: int = 3) -> Dict[str, Any]:
    collection = get_chroma_collection()
    return collection.get(limit=limit, include=["metadatas", "documents"])


def chroma_reset_collection() -> None:
    if CHROMA_PERSIST_DIR.exists():
        shutil.rmtree(CHROMA_PERSIST_DIR, ignore_errors=True)

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(CHROMA_PERSIST_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)