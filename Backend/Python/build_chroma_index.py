from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any, Dict, List

os.environ["ANONYMIZED_TELEMETRY"] = "FALSE"

import requests
from dotenv import load_dotenv

from rag_chromadb_service import get_chroma_collection, chroma_reset_collection

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


def load_pickle_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Ficheiro de embeddings não encontrado: {path}")

    with open(path, "rb") as fh:
        payload = pickle.load(fh)

    if not isinstance(payload, dict):
        raise ValueError("O ficheiro .pkl não contém um dicionário válido.")

    if "records" not in payload:
        raise ValueError("O ficheiro .pkl não contém a chave 'records'.")

    return payload


def build_document_text(record: Dict[str, Any]) -> str:
    parts = [
        f"Citação: {record.get('citation_label', '')}",
        f"Documento: {record.get('short_name', '')}",
        f"Tipo: {record.get('section_type', '')}",
        f"Secção: {record.get('section_number', '')}",
        f"Título: {record.get('section_title', '')}",
        f"Páginas: {record.get('page_start', '')} - {record.get('page_end', '')}",
        f"Texto: {record.get('text', '')}",
    ]
    return "\n".join(parts).strip()


def record_metadata(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "citation_label": str(record.get("citation_label", ""))[:500],
        "short_name": str(record.get("short_name", ""))[:200],
        "section_type": str(record.get("section_type", ""))[:100],
        "section_number": str(record.get("section_number", ""))[:200],
        "section_title": str(record.get("section_title", ""))[:500],
        "page_start": int(record["page_start"]) if record.get("page_start") not in (None, "") else -1,
        "page_end": int(record["page_end"]) if record.get("page_end") not in (None, "") else -1,
    }


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    response = requests.post(
        f"{OLLAMA_HOST}/api/embed",
        json={
            "model": OLLAMA_EMBED_MODEL,
            "input": texts,
        },
        timeout=300,
    )
    response.raise_for_status()

    payload = response.json()
    embeddings = payload.get("embeddings")

    if not embeddings or not isinstance(embeddings, list):
        raise RuntimeError("O Ollama não devolveu embeddings válidos.")

    return embeddings


def main() -> None:
    payload = load_pickle_payload(EMBEDDINGS_PATH)
    records = payload["records"]

    if not isinstance(records, list) or not records:
        raise ValueError("Não existem records válidos para indexar.")

    print("[Chroma] A limpar coleção anterior...")
    chroma_reset_collection()
    collection = get_chroma_collection()

    batch_size = 32
    total = len(records)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = records[start:end]

        ids = [f"doc_{i}" for i in range(start, end)]
        documents = [build_document_text(r) for r in batch]
        metadatas = [record_metadata(r) for r in batch]
        embeddings = embed_texts(documents)

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        print(f"[Chroma] Indexados {end}/{total}")

    print("[Chroma] Indexação concluída com sucesso.")


if __name__ == "__main__":
    main()