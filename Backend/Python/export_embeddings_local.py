"""
Script de exportação de embeddings locais para ficheiro no projeto BridgeMedAI.

Este ficheiro implementa o pipeline que:
- lê os chunks normativos já existentes na base de dados SQL Server;
- gera embeddings com Ollama;
- constrói uma estrutura em memória com:
  - metadados dos chunks (`records`);
  - matriz de embeddings (`embeddings`);
- serializa essa estrutura para um ficheiro `.pkl`.

Objetivo principal:
- permitir um modo de retrieval sem dependência de ChromaDB;
- acelerar testes locais;
- disponibilizar um payload simples e reutilizável para pesquisa semântica.

Estrutura final esperada no ficheiro:
    {
        "records": [...],
        "embeddings": np.ndarray(...)
    }

Este ficheiro é consumido depois por:
- `search_embeddings_local.py`
- `chat_rag_local_no_chroma.py`
- `api_rag_service.py`
"""

import os
import pickle
from pathlib import Path

import numpy as np
import pyodbc
import ollama
from dotenv import load_dotenv


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
EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


def get_sql_connection():
    """
    Cria uma ligação ao SQL Server configurado no projeto.

    A ligação usa as variáveis definidas no `.env` para montar a connection string.

    Returns:
        pyodbc.Connection:
            Ligação ativa à base de dados.
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


def get_chunks():
    """
    Lê todos os chunks normativos armazenados na base de dados.

    Cada registo devolvido inclui:
    - ID do chunk;
    - documento de origem;
    - tipo e número de secção;
    - título da secção;
    - intervalo de páginas;
    - texto do chunk;
    - citação associada.

    Esta informação é necessária para:
    - construir o payload dos `records`;
    - manter rastreabilidade entre embeddings e fontes normativas.

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
    Divide uma lista em batches de tamanho fixo.

    O processamento em batches é útil para:
    - reduzir carga em memória;
    - evitar pedidos demasiado grandes ao Ollama;
    - acompanhar o progresso do processamento.

    Args:
        items:
            Lista de itens a dividir.
        batch_size:
            Tamanho máximo de cada batch.

    Yields:
        list:
            Batch seguinte da sequência.
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def main():
    """
    Executa o pipeline principal de exportação de embeddings locais.

    Etapas:
    1. ler chunks da base de dados;
    2. validar se existem dados;
    3. processar os chunks em batches;
    4. gerar embeddings via Ollama;
    5. construir a lista de `records`;
    6. acumular embeddings num array `numpy`;
    7. serializar o payload final para ficheiro `.pkl`.

    O payload final fica com duas chaves principais:
    - `records`: lista de metadados por chunk;
    - `embeddings`: matriz de embeddings.

    Returns:
        None
    """
    rows = get_chunks()

    if not rows:
        print("Não há chunks na base de dados.")
        return

    print(f"[INFO] {len(rows)} chunks encontrados.")

    records = []
    embeddings = []

    total = 0

    # -----------------------------------------------------------------------
    # Processamento por batches
    # -----------------------------------------------------------------------
    for batch in batch_items(rows, batch_size=64):
        texts = [row.chunk_text for row in batch]

        # -------------------------------------------------------------------
        # Geração de embeddings do batch
        # -------------------------------------------------------------------
        result = ollama.embed(
            model=OLLAMA_EMBED_MODEL,
            input=texts
        )

        batch_embeddings = result["embeddings"]

        # -------------------------------------------------------------------
        # Construção dos registos alinhados com os embeddings
        # -------------------------------------------------------------------
        for row, emb in zip(batch, batch_embeddings):
            records.append({
                "chunk_id": int(row.chunk_id),
                "short_name": row.short_name,
                "section_type": row.section_type,
                "section_number": row.section_number or "",
                "section_title": row.section_title or "",
                "page_start": int(row.page_start) if row.page_start is not None else -1,
                "page_end": int(row.page_end) if row.page_end is not None else -1,
                "chunk_text": row.chunk_text,
                "citation_label": row.citation_label or ""
            })
            embeddings.append(np.array(emb, dtype=np.float32))

        total += len(batch)
        print(f"[OK] Processados {total}/{len(rows)} chunks")

    # -----------------------------------------------------------------------
    # Conversão da lista de embeddings numa matriz NumPy
    # -----------------------------------------------------------------------
    # Esta matriz é a forma mais conveniente para cálculos vetoriais rápidos
    # no pipeline local de retrieval.
    embeddings_matrix = np.vstack(embeddings)

    payload = {
        "records": records,
        "embeddings": embeddings_matrix
    }

    # -----------------------------------------------------------------------
    # Escrita do payload final para ficheiro
    # -----------------------------------------------------------------------
    with open(EMBEDDINGS_PATH, "wb") as f:
        pickle.dump(payload, f)

    print(f"[DONE] Embeddings guardados em: {EMBEDDINGS_PATH}")
    print("Shape:", embeddings_matrix.shape)


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()