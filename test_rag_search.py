import chromadb
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_collection("carrera_ti_indoamerica_collection")

q = "como son las practicas?"
emb = embedder.encode(q).tolist()
res = collection.query(query_embeddings=[emb], n_results=42)
for i in range(len(res['documents'][0])):
    dist = res['distances'][0][i]
    doc = res['documents'][0][i]
    if "Prácticas de Servicio Comunitario" in doc or "Prácticas Preprofesionales" in doc:
        print(f"FOUND at rank {i+1} - Dist: {dist:.2f} | Text: {doc[:100]}")
