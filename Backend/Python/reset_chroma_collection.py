"""
Script de remoção da collection principal do ChromaDB no projeto BridgeMedAI.

Este ficheiro apaga apenas a collection vetorial usada para armazenar os chunks
normativos indexados localmente.

Objetivo principal:
- permitir reconstruir a collection `regulations_chunks` do zero;
- limpar indexações antigas ou inconsistentes;
- facilitar ciclos de teste e reindexação.

Diferença face ao reset total do Chroma:
- este script remove apenas uma collection específica;
- não afeta necessariamente outras collections que possam existir no mesmo
  diretório persistente.

Fluxo resumido:
1. carregar configuração do `.env`;
2. abrir o cliente persistente do ChromaDB;
3. tentar apagar a collection `regulations_chunks`;
4. informar no terminal o resultado da operação.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import chromadb


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()
COLLECTION_NAME = "regulations_chunks"


# ---------------------------------------------------------------------------
# Inicialização do cliente ChromaDB persistente
# ---------------------------------------------------------------------------
# O cliente aponta para o diretório local onde o Chroma guarda os seus dados.
client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))


try:
    # -----------------------------------------------------------------------
    # Remoção da collection principal do projeto
    # -----------------------------------------------------------------------
    # Se a collection existir, será apagada.
    # Se não existir, a exceção será apanhada e será mostrada uma mensagem.
    client.delete_collection(name=COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}' apagada com sucesso.")
except Exception as e:
    print(f"Não foi possível apagar a collection (pode não existir): {e}")