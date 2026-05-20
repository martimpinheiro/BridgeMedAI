"""
Reset da collection principal do ChromaDB no projeto BridgeMedAI.

Funciona tanto em modo HTTP como em modo persistente local,
usando sempre a configuração central de rag_chromadb_service.py.
"""

from rag_chromadb_service import (
    chroma_reset_collection,
    get_chroma_collection,
    CHROMA_COLLECTION_NAME,
    CHROMA_MODE,
    CHROMA_HOST,
    CHROMA_PORT,
)

def main():
    print(f"[INFO] Chroma mode: {CHROMA_MODE}")
    print(f"[INFO] Collection: {CHROMA_COLLECTION_NAME}")

    if CHROMA_MODE == "http":
        print(f"[INFO] Chroma host: {CHROMA_HOST}:{CHROMA_PORT}")

    chroma_reset_collection()

    collection = get_chroma_collection()
    print(f"[OK] Collection '{CHROMA_COLLECTION_NAME}' apagada/recriada com sucesso.")
    print(f"[INFO] Total atual na collection: {collection.count()}")

if __name__ == "__main__":
    main()