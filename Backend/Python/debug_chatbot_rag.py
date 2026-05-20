import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from api_rag_service import answer_question


def main():
    if len(sys.argv) < 2:
        print('Uso: python Backend/Python/debug_chatbot_rag.py "pergunta"')
        return

    question = sys.argv[1]

    result = answer_question(question)

    print("\n==============================")
    print("PERGUNTA")
    print("==============================")
    print(question)

    print("\n==============================")
    print("INTENT")
    print("==============================")
    print(result.get("intent"))

    print("\n==============================")
    print("DOCUMENTOS-ALVO")
    print("==============================")
    print(result.get("target_docs"))

    print("\n==============================")
    print("BACKEND")
    print("==============================")
    print(result.get("retrieval_backend"))

    print("\n==============================")
    print("FONTES USADAS NA GERAÇÃO")
    print("==============================")
    for i, src in enumerate(result.get("generation_sources", []), start=1):
        print(f"\n--- Fonte {i} ---")
        print("Citação:", src.get("citation_label"))
        print("Documento:", src.get("short_name"))
        print("Tipo:", src.get("section_type"))
        print("Secção:", src.get("section_number"))
        print("Título:", src.get("section_title"))
        print("Score:", src.get("score_adjusted"))

    print("\n==============================")
    print("RESPOSTA")
    print("==============================")
    print(result.get("answer"))


if __name__ == "__main__":
    main()