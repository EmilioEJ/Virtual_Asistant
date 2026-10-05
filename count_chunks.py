import chromadb
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_collection("carrera_ti_indoamerica_collection")
print(f"Total chunks: {collection.count()}")
