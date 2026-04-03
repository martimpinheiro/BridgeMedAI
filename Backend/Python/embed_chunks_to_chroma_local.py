"""
Script de indexação de chunks normativos no ChromaDB para o projeto BridgeMedAI.

Este ficheiro implementa o pipeline de exportação de chunks da base de dados
relacional para uma base vetorial local (ChromaDB), usando embeddings gerados
via Ollama.

Objetivo principal:
- ler os chunks já estruturados na base de dados SQL Server;
- gerar embeddings para cada chunk;
- armazenar os chunks, metadados e embeddings numa collection persistente
  do ChromaDB.

Este script é útil para:
- preparar a base vetorial local usada por pesquisas semânticas;
- reconstruir a collection após alterações aos documentos ou ao processo de chunking;
- testar localmente pipelines RAG baseados em ChromaDB.

Fluxo resumido:
1. carregar variáveis do `.env`;
2. ligar ao SQL Server;
3. ler os chunks da base de dados;
4. dividir os dados em batches;
5. gerar embeddings com Ollama;
6. criar/atualizar a collection no ChromaDB;
7. inserir os dados na collection via `upsert`.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import pyodbc
import chromadb
import ollama


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()


# ---------------------------------------------------------------------------
# Nome da collection vetorial
# ---------------------------------------------------------------------------
# Esta collection é usada pelo restante pipeline local com Chroma.
COLLECTION_NAME = "regulations_chunks"


def get_sql_connection():
    """
    Cria uma ligação à base de dados SQL Server usada pelo projeto.

    A ligação usa as variáveis de ambiente definidas no `.env`, nomeadamente:
    - DB_SERVER
    - DB_NAME
    - DB_TRUSTED_CONNECTION
    - DB_ENCRYPT

    Returns:
        pyodbc.Connection:
            Ligação ativa ao SQL Server.
    """
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
    """
    Lê da base de dados todos os chunks normativos já processados.

    A query junta:
    - `document_chunks`
    - `document_sections`
    - `documents`

    Isto permite obter, por chunk:
    - ID único;
    - documento de origem;
    - tipo e número de secção;
    - título da secção;
    - intervalo de páginas;
    - texto do chunk;
    - citação associada.

    Returns:
        list:
            Lista de linhas devolvidas pelo SQL Server.
    """
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
    """
    Divide uma sequência em batches de tamanho fixo.

    Isto é útil para:
    - evitar pedidos demasiado grandes ao modelo de embeddings;
    - controlar consumo de memória;
    - facilitar indexação progressiva.

    Args:
        items:
            Lista de itens a dividir.
        batch_size:
            Número máximo de elementos por batch.

    Yields:
        list:
            Batch seguinte de elementos.
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def main():
    """
    Executa o pipeline principal de indexação de chunks no ChromaDB.

    Etapas:
    1. ler chunks da base de dados;
    2. validar se existem dados para indexar;
    3. abrir o cliente persistente do ChromaDB;
    4. criar ou reutilizar a collection;
    5. processar os chunks em batches;
    6. gerar embeddings via Ollama;
    7. fazer `upsert` dos dados na collection.

    Para cada chunk são guardados:
    - ID;
    - texto;
    - metadados;
    - embedding.

    Returns:
        None
    """
    rows = get_chunks_from_db()

    if not rows:
        print("Não há chunks na base de dados.")
        return

    print(f"[INFO] {len(rows)} chunks encontrados.")

    # -----------------------------------------------------------------------
    # Inicialização do cliente ChromaDB
    # -----------------------------------------------------------------------
    # Usa armazenamento persistente em disco, para que a collection não se
    # perca entre execuções.
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

    total = 0

    # -----------------------------------------------------------------------
    # Processamento por batches
    # -----------------------------------------------------------------------
    for batch in batch_items(rows, batch_size=64):
        texts = [row.chunk_text for row in batch]

        # -------------------------------------------------------------------
        # Geração de embeddings dos textos do batch
        # -------------------------------------------------------------------
        embed_result = ollama.embed(
            model=OLLAMA_EMBED_MODEL,
            input=texts
        )

        embeddings = embed_result["embeddings"]

        ids = []
        documents = []
        metadatas = []

        # -------------------------------------------------------------------
        # Preparação dos dados para inserção na collection
        # -------------------------------------------------------------------
        for row in batch:
            ids.append(str(row.chunk_id))
            documents.append(row.chunk_text)
            metadatas.append({
                "short_name": row.short_name,
                "section_type": row.section_type,
                "section_number": row.section_number or "",
                "section_title": row.section_title or "",
                "page_start": int(row.page_start) if row.page_start is not None else -1,
                "page_end": int(row.page_end) if row.page_end is not None else -1,
                "citation_label": row.citation_label or ""
            })

        # -------------------------------------------------------------------
        # Inserção/atualização na collection
        # -------------------------------------------------------------------
        # `upsert` garante que:
        # - novos IDs são inseridos;
        # - IDs já existentes são atualizados.
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

        total += len(batch)
        print(f"[OK] Indexados {total}/{len(rows)} chunks")

    print(f"[DONE] Collection '{COLLECTION_NAME}' criada/atualizada com sucesso.")


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()