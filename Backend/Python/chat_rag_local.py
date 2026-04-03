"""
Script local de teste de chat RAG com ChromaDB no projeto BridgeMedAI.

Este ficheiro permite executar uma pergunta diretamente pela linha de comandos,
sem passar pela API FastAPI, usando:

- uma collection local no ChromaDB;
- embeddings gerados via Ollama;
- um modelo de chat local no Ollama.

Objetivo principal:
- testar rapidamente o pipeline de recuperação + geração;
- validar se a collection vetorial está corretamente populada;
- inspecionar o comportamento da resposta final do modelo.

Fluxo resumido:
1. carregar variáveis de ambiente;
2. receber a pergunta via linha de comandos;
3. ligar ao ChromaDB local;
4. gerar embedding da pergunta;
5. recuperar os chunks mais próximos;
6. construir contexto textual;
7. enviar contexto + instruções ao modelo de chat;
8. imprimir a resposta final no terminal.

Este script é útil para debugging local e testes manuais do sistema.
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
# O projeto espera encontrar o ficheiro `.env` dentro da pasta Backend.
# A partir desse ficheiro são carregadas configurações como:
# - nome do modelo de embeddings;
# - nome do modelo de chat;
# - diretoria persistente do ChromaDB.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL")
CHROMA_PERSIST_DIR = (
    PROJECT_ROOT / os.getenv("CHROMA_PERSIST_DIR", "Backend/chroma_data")
).resolve()


# ---------------------------------------------------------------------------
# Nome da collection vetorial
# ---------------------------------------------------------------------------
# Esta é a collection onde os chunks normativos foram previamente indexados.
COLLECTION_NAME = "regulations_chunks"


# ---------------------------------------------------------------------------
# Prompt de sistema
# ---------------------------------------------------------------------------
# Este prompt define o comportamento global esperado do modelo:
# - responder apenas com base no contexto;
# - não inventar artigos ou obrigações;
# - citar, sempre que possível, no formato esperado.
SYSTEM_PROMPT = """
És um assistente regulatório do projeto BridgeMedAI.
Responde apenas com base no contexto fornecido.
Se o contexto não for suficiente, diz claramente que não tens base suficiente.
Sempre que possível, cita as fontes no formato:
- MDR <secção>
- AI_ACT <secção>
Não inventes artigos, requisitos ou obrigações.
Responde em português de Portugal.
"""


def build_context(results):
    """
    Constrói o contexto textual a partir dos resultados devolvidos pelo ChromaDB.

    O Chroma devolve a query em formato estruturado, incluindo:
    - documentos (texto dos chunks);
    - metadados;
    - distâncias.

    Esta função transforma os documentos recuperados numa string única formatada
    com informação suficiente para o modelo perceber:
    - de que documento vem cada excerto;
    - qual o tipo de secção;
    - que páginas e citações lhe estão associadas.

    Args:
        results:
            Resultado bruto devolvido por `collection.query(...)`.

    Returns:
        str:
            Texto consolidado com todas as fontes recuperadas.
    """
    docs = results["documents"][0]
    metas = results["metadatas"][0]

    context_parts = []

    for doc, meta in zip(docs, metas):
        part = f"""
[FONTE]
Documento: {meta.get("short_name")}
Tipo: {meta.get("section_type")}
Secção: {meta.get("section_number")}
Título: {meta.get("section_title")}
Páginas: {meta.get("page_start")} - {meta.get("page_end")}
Citação: {meta.get("citation_label")}

Texto:
{doc}
"""
        context_parts.append(part.strip())

    return "\n\n".join(context_parts)


def main():
    """
    Executa o fluxo principal do script local de chat RAG.

    Etapas:
    1. validar se foi fornecida uma pergunta via linha de comandos;
    2. abrir a collection do ChromaDB;
    3. gerar embedding da pergunta com Ollama;
    4. pesquisar os chunks mais próximos;
    5. construir o contexto textual;
    6. montar o prompt final;
    7. gerar a resposta via modelo de chat;
    8. imprimir a resposta no terminal.

    Uso esperado:
        python .\\Python\\chat_rag_local.py "pergunta"

    Returns:
        None
    """
    if len(sys.argv) < 2:
        print('Uso: python .\\Python\\chat_rag_local.py "pergunta"')
        return

    user_question = sys.argv[1]

    # -----------------------------------------------------------------------
    # Ligação à base vetorial local (ChromaDB)
    # -----------------------------------------------------------------------
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    collection = chroma_client.get_collection(name=COLLECTION_NAME)

    # -----------------------------------------------------------------------
    # Geração do embedding da pergunta
    # -----------------------------------------------------------------------
    # Este embedding será usado para procurar os chunks semanticamente mais próximos.
    query_embedding = ollama.embed(
        model=OLLAMA_EMBED_MODEL,
        input=user_question
    )["embeddings"][0]

    # -----------------------------------------------------------------------
    # Pesquisa vetorial na collection
    # -----------------------------------------------------------------------
    # `n_results=5` limita o número de chunks recuperados.
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5
    )

    # -----------------------------------------------------------------------
    # Construção do contexto textual
    # -----------------------------------------------------------------------
    context = build_context(results)

    # -----------------------------------------------------------------------
    # Prompt final enviado ao modelo
    # -----------------------------------------------------------------------
    # Junta:
    # - pergunta do utilizador;
    # - contexto recuperado;
    # - instruções finais de comportamento.
    prompt = f"""
Pergunta do utilizador:
{user_question}

Contexto recuperado:
{context}

Instruções:
- Responde apenas com base no contexto.
- Resume de forma clara.
- Se houver base insuficiente, diz isso.
- No fim, indica as citações usadas.
"""

    # -----------------------------------------------------------------------
    # Geração da resposta via modelo de chat local
    # -----------------------------------------------------------------------
    response = ollama.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=False
    )

    print("\nResposta:\n")
    print(response["message"]["content"])


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
# Garante que o ficheiro pode ser executado diretamente pela linha de comandos.
if __name__ == "__main__":
    main()