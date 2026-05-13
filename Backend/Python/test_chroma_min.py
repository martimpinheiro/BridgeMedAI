from rag_chromadb_service import get_chroma_collection

collection = get_chroma_collection()
print("Collection obtida.")
print("Count:", collection.count())