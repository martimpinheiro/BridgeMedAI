"""
Script de teste local à integração com Ollama no projeto BridgeMedAI.

Este ficheiro faz uma verificação rápida de conectividade funcional com o Ollama,
testando separadamente:

- o modelo de embeddings configurado;
- o modelo de chat configurado.

Objetivo principal:
- validar se o Ollama está acessível localmente;
- confirmar que os nomes dos modelos no `.env` são válidos;
- despistar problemas básicos antes de testar retrieval, indexação ou chat RAG.

Fluxo resumido:
1. carregar configuração do `.env`;
2. imprimir os nomes dos modelos configurados;
3. gerar um embedding de teste;
4. verificar a dimensão do embedding;
5. executar uma chamada simples ao modelo de chat;
6. imprimir a resposta.

Este script é útil como teste de sanidade do ambiente local.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import ollama


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL")


# ---------------------------------------------------------------------------
# Impressão da configuração ativa
# ---------------------------------------------------------------------------
# Isto ajuda a confirmar rapidamente quais os modelos que o script está a usar.
print("Modelo embeddings:", OLLAMA_EMBED_MODEL)
print("Modelo chat:", OLLAMA_CHAT_MODEL)


# ---------------------------------------------------------------------------
# Teste do modelo de embeddings
# ---------------------------------------------------------------------------
# O objetivo é verificar:
# - se o modelo existe;
# - se o Ollama consegue processar um input simples;
# - se a resposta inclui um embedding válido.
embed_result = ollama.embed(
    model=OLLAMA_EMBED_MODEL,
    input="Teste de embedding para BridgeMedAI"
)

print("Embedding OK")
print("Dimensão:", len(embed_result["embeddings"][0]))


# ---------------------------------------------------------------------------
# Teste do modelo de chat
# ---------------------------------------------------------------------------
# Este teste pede uma resposta extremamente simples para validar a capacidade
# do modelo gerar texto e devolver uma estrutura compatível.
chat_result = ollama.chat(
    model=OLLAMA_CHAT_MODEL,
    messages=[{"role": "user", "content": "Responde apenas com a palavra OK"}],
)

print("Chat OK")
print("Resposta:", chat_result["message"]["content"])