"""
Script local de pesquisa semântica sem ChromaDB para o projeto BridgeMedAI.

Este ficheiro executa uma pesquisa sobre o payload local de embeddings
armazenado em ficheiro (`local_embeddings.pkl`), sem depender de uma base
vetorial externa como o ChromaDB.

Objetivos principais:
- testar localmente o pipeline de retrieval baseado em embeddings;
- validar a lógica de ranking heurístico implementada em `rag_router_utils.py`;
- inspecionar os scores base e os scores ajustados das fontes recuperadas;
- perceber que intenção e documentos-alvo foram inferidos a partir da pergunta.

Fluxo resumido:
1. carregar configuração do `.env`;
2. receber a query via linha de comandos;
3. validar o modelo de embeddings configurado;
4. carregar o ficheiro local de embeddings;
5. executar o retrieval semântico e heurístico;
6. imprimir os resultados ordenados por relevância.

Este script é útil para debugging e validação da lógica interna do sistema
sem depender da API nem do ChromaDB.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from rag_router_utils import (
    validate_embeddings_payload,
    retrieve_relevant_indices,
)


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


def main():
    """
    Executa a pesquisa semântica local sobre o ficheiro de embeddings.

    Etapas:
    1. validar se a query foi fornecida;
    2. validar se o modelo de embeddings está configurado;
    3. carregar e validar o payload local de embeddings;
    4. executar o retrieval semântico + heurístico;
    5. imprimir no terminal:
       - pergunta;
       - intenção detetada;
       - documentos-alvo;
       - resultados recuperados com score bruto e ajustado.

    Uso esperado:
        python .\\Python\\search_embeddings_local.py "texto da pesquisa"

    Returns:
        None
    """
    if len(sys.argv) < 2:
        print('Uso: python .\\Python\\search_embeddings_local.py "texto da pesquisa"')
        return

    if not OLLAMA_EMBED_MODEL:
        print("[ERRO] Falta OLLAMA_EMBED_MODEL no .env")
        return

    query_text = sys.argv[1].strip()

    if not query_text:
        print("[ERRO] O texto da pesquisa não pode estar vazio.")
        return

    try:
        # -------------------------------------------------------------------
        # Carregamento e validação do payload de embeddings
        # -------------------------------------------------------------------
        payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
        records = payload["records"]
        embeddings = payload["embeddings"]

        # -------------------------------------------------------------------
        # Execução do retrieval semântico com heurísticas regulatórias
        # -------------------------------------------------------------------
        selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
            question=query_text,
            records=records,
            embeddings=embeddings,
            embed_model=OLLAMA_EMBED_MODEL
        )

        print("\nPergunta:", query_text)
        print("Intent detetada:", plan["intent"])
        print("Documentos-alvo:", plan["target_docs"] if plan["target_docs"] else "sem filtro fixo")
        print("\nResultados encontrados:\n")

        # -------------------------------------------------------------------
        # Impressão detalhada dos resultados
        # -------------------------------------------------------------------
        # Cada resultado mostra:
        # - score base (similaridade vetorial);
        # - score ajustado (após heurísticas);
        # - documento e secção;
        # - citação;
        # - preview do texto recuperado.
        for rank, idx in enumerate(selected_indices, start=1):
            record = records[idx]
            base_score = float(base_scores[idx])
            adjusted_score = float(adjusted_scores[idx])

            print(f"--- Resultado {rank} ---")
            print("Score bruto:", round(base_score, 4))
            print("Score ajustado:", round(adjusted_score, 4))
            print("Documento:", record.get("short_name"))
            print("Tipo:", record.get("section_type"))
            print("Secção:", record.get("section_number"))
            print("Título:", record.get("section_title"))
            print("Páginas:", record.get("page_start"), "-", record.get("page_end"))
            print("Citação:", record.get("citation_label"))
            print("Texto:", record.get("chunk_text", "")[:500], "...\n")

    except FileNotFoundError as e:
        print(f"[ERRO] {e}")
    except ValueError as e:
        print(f"[ERRO] {e}")
    except Exception as e:
        print(f"[ERRO] Falha na pesquisa semântica: {e}")


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()