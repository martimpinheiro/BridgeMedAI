"""
Script de reset total da base persistente do ChromaDB no projeto BridgeMedAI.

Este ficheiro executa um reset completo do armazenamento local do ChromaDB,
apagando todas as collections e o respetivo estado persistido nesse diretório.

Objetivo principal:
- limpar integralmente a base vetorial local;
- resolver estados inconsistentes;
- preparar um recomeço completo da indexação vetorial.

Diferença face ao `reset_chroma_collection.py`:
- `reset_chroma_collection.py` remove apenas uma collection específica;
- este script faz reset global do cliente persistente configurado.

Atenção:
- este reset afeta todo o armazenamento Chroma associado ao diretório indicado;
- deve ser usado com cuidado, sobretudo se houver múltiplas collections úteis
  no mesmo diretório.

Fluxo resumido:
1. carregar configuração do `.env`;
2. abrir o cliente persistente do ChromaDB com `allow_reset=True`;
3. executar `client.reset()`;
4. informar no terminal que o reset foi concluído.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings


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


# ---------------------------------------------------------------------------
# Inicialização do cliente ChromaDB com reset permitido
# ---------------------------------------------------------------------------
# O parâmetro `allow_reset=True` é necessário para permitir a operação global
# de reset do armazenamento persistente.
client = chromadb.PersistentClient(
    path=str(CHROMA_PERSIST_DIR),
    settings=Settings(allow_reset=True)
)


# ---------------------------------------------------------------------------
# Reset total do estado persistente
# ---------------------------------------------------------------------------
# Esta operação remove todas as collections e limpa o armazenamento associado
# ao diretório configurado.
client.reset()
print("Chroma resetado com sucesso.")