"""
Script local de pesquisa semântica no ChromaDB para o projeto BridgeMedAI.

Este ficheiro permite testar rapidamente a recuperação vetorial de chunks
normativos indexados numa collection persistente do ChromaDB.

Objetivos principais:
- validar se a collection foi criada corretamente;
- verificar se os embeddings estão a produzir resultados relevantes;
- inspecionar manualmente os metadados e textos devolvidos pela pesquisa.

Fluxo resumido:
1. carregar configuração do `.env`;
2. receber uma query via linha de comandos;
3. abrir a collection local do ChromaDB;
4. gerar o embedding da query com Ollama;
5. executar a pesquisa vetorial;
6. imprimir os resultados no terminal.

Este script é útil para debugging local e validação do pipeline de indexação.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import chromadb
import ollama


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()


# ---------------------------------------------------------------------------
# Nome da collection vetorial
# ---------------------------------------------------------------------------
# Esta collection contém os chunks normativos previamente indexados.
COLLECTION_NAME = "regulations_chunks"


def main():
    """
    Executa a pesquisa semântica local sobre o ChromaDB.

    Etapas:
    1. validar se foi fornecida uma query;
    2. abrir a base vetorial persistente;
    3. obter a collection configurada;
    4. gerar embedding da query;
    5. executar `collection.query(...)`;
    6. imprimir os resultados no terminal.

    Uso esperado:
        python .\\Python\\search_chroma_local.py "texto da pesquisa"

    Returns:
        None
    """
    if len(sys.argv) < 2:
        print('Uso: python .\\Python\\search_chroma_local.py "texto da pesquisa"')
        return

    query_text = sys.argv[1]

    # -----------------------------------------------------------------------
    # Ligação ao cliente ChromaDB persistente
    # -----------------------------------------------------------------------
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    collection = chroma_client.get_collection(name=COLLECTION_NAME)

    # -----------------------------------------------------------------------
    # Geração do embedding da query
    # -----------------------------------------------------------------------
    # Este embedding será comparado com os embeddings já guardados na collection.
    query_embedding = ollama.embed(
        model=OLLAMA_EMBED_MODEL,
        input=query_text
    )["embeddings"][0]

    # -----------------------------------------------------------------------
    # Pesquisa vetorial
    # -----------------------------------------------------------------------
    # `n_results=5` limita a pesquisa aos 5 chunks semanticamente mais próximos.
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5
    )

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    print("\nPergunta:", query_text)
    print("\nResultados encontrados:\n")

    # -----------------------------------------------------------------------
    # Impressão formatada dos resultados
    # -----------------------------------------------------------------------
    # Cada resultado mostra:
    # - ID do chunk;
    # - distância vetorial;
    # - metadados normativos;
    # - preview do texto.
    for i, (rid, doc, meta, dist) in enumerate(zip(ids, documents, metadatas, distances), start=1):
        print(f"--- Resultado {i} ---")
        print("ID:", rid)
        print("Distância:", dist)
        print("Documento:", meta.get("short_name"))
        print("Tipo:", meta.get("section_type"))
        print("Secção:", meta.get("section_number"))
        print("Título:", meta.get("section_title"))
        print("Páginas:", meta.get("page_start"), "-", meta.get("page_end"))
        print("Citação:", meta.get("citation_label"))
        print("Texto:", doc[:500], "...\n")


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()