from rag_chromadb_service import get_chroma_collection

collection = get_chroma_collection()

print("Collection obtida.")
print("Total:", collection.count())

print("\n=== Regras MDR no Chroma ===")
try:
    result = collection.get(
        where={"section_type": "rule"},
        limit=20,
        include=["metadatas", "documents"],
    )

    print("Encontradas:", len(result.get("ids", [])))

    for i, meta in enumerate(result.get("metadatas", []), start=1):
        doc = result.get("documents", [""])[i - 1]
        print("\n--- Regra", i, "---")
        print("ID:", result["ids"][i - 1])
        print("Citação:", meta.get("citation_label"))
        print("Documento:", meta.get("short_name"))
        print("Tipo:", meta.get("section_type"))
        print("Secção:", meta.get("section_number"))
        print("Título:", meta.get("section_title"))
        print("Páginas:", meta.get("page_start"), "-", meta.get("page_end"))
        print("Texto:", doc[:700].replace("\n", " "))

except Exception as exc:
    print("Erro ao pesquisar regras:", exc)


print("\n=== Pesquisa direta por termómetro / não invasivo ===")
queries = [
    "Regra 1 dispositivos não invasivos MDR Anexo VIII",
    "Regra 10 dispositivo ativo medição temperatura corporal MDR Anexo VIII",
    "termómetro digital medição temperatura corporal classificação MDR",
]

import ollama
import os
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"
load_dotenv(dotenv_path=ENV_PATH)

OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")

for q in queries:
    print("\n\nQUERY:", q)

    emb = ollama.embed(
        model=OLLAMA_EMBED_MODEL,
        input=q,
    )["embeddings"][0]

    res = collection.query(
        query_embeddings=[emb],
        n_results=10,
        where={"short_name": "MDR"},
        include=["documents", "metadatas", "distances"],
    )

    for i, meta in enumerate(res.get("metadatas", [[]])[0], start=1):
        doc = res.get("documents", [[]])[0][i - 1]
        dist = res.get("distances", [[]])[0][i - 1]
        print("\n--- Resultado", i, "---")
        print("Distância:", dist)
        print("Citação:", meta.get("citation_label"))
        print("Tipo:", meta.get("section_type"))
        print("Secção:", meta.get("section_number"))
        print("Título:", meta.get("section_title"))
        print("Páginas:", meta.get("page_start"), "-", meta.get("page_end"))
        print("Texto:", doc[:500].replace("\n", " "))