"""
Script de indexação de chunks normativos no ChromaDB para o projeto BridgeMedAI.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import pyodbc
import ollama

from rag_chromadb_service import (
    get_chroma_collection,
    chroma_reset_collection,
    CHROMA_COLLECTION_NAME,
    CHROMA_MODE,
    CHROMA_HOST,
    CHROMA_PORT,
)


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")


def get_sql_connection():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
        f"Encrypt={DB_ENCRYPT};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def get_chunks_from_db():
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.id AS chunk_id,
            d.short_name,
            s.section_type,
            s.section_number,
            s.section_title,
            c.page_start,
            c.page_end,
            c.chunk_text,
            c.citation_label
        FROM dbo.document_chunks c
        INNER JOIN dbo.document_sections s
            ON c.section_id = s.id
        INNER JOIN dbo.documents d
            ON c.document_id = d.id
        ORDER BY d.id, s.id, c.chunk_index
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def batch_items(items, batch_size=64):
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def clean_metadata_value(value, default=""):
    if value is None:
        return default
    return value


def main():
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    rows = get_chunks_from_db()

    if not rows:
        print("Não há chunks na base de dados.")
        return

    print(f"[INFO] {len(rows)} chunks encontrados.")
    print(f"[INFO] Chroma mode: {CHROMA_MODE}")
    print(f"[INFO] Chroma host: {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"[INFO] Collection: {CHROMA_COLLECTION_NAME}")

    # Muito importante:
    # em modo HTTP, isto apaga/recria a collection através do servidor Chroma,
    # não escrevendo diretamente na pasta do índice.
    chroma_reset_collection()
    collection = get_chroma_collection()

    total = 0

    for batch in batch_items(rows, batch_size=64):
        texts = [row.chunk_text for row in batch]

        embed_result = ollama.embed(
            model=OLLAMA_EMBED_MODEL,
            input=texts,
        )

        embeddings = embed_result["embeddings"]

        ids = []
        documents = []
        metadatas = []

        for row in batch:
            ids.append(str(row.chunk_id))
            documents.append(row.chunk_text)
            metadatas.append({
                "chunk_id": str(row.chunk_id),
                "short_name": clean_metadata_value(row.short_name),
                "section_type": clean_metadata_value(row.section_type),
                "section_number": clean_metadata_value(row.section_number),
                "section_title": clean_metadata_value(row.section_title),
                "page_start": int(row.page_start) if row.page_start is not None else -1,
                "page_end": int(row.page_end) if row.page_end is not None else -1,
                "citation_label": clean_metadata_value(row.citation_label),
            })

        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        total += len(batch)
        print(f"[OK] Indexados {total}/{len(rows)} chunks")

    print(f"[DONE] Collection '{CHROMA_COLLECTION_NAME}' criada/atualizada com sucesso.")
    print(f"[INFO] Total na collection: {collection.count()}")


if __name__ == "__main__":
    main()