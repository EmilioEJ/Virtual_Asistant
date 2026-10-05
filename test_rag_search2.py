import chromadb
from sentence_transformers import SentenceTransformer

embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_collection("carrera_ti_indoamerica_collection")

q = "Practicas preprofesionales y de servicio comunitario en la malla curricular"
emb = embedder.encode(q).tolist()
res = collection.query(query_embeddings=[emb], n_results=10)
for i in range(len(res['documents'][0])):
    dist = res['distances'][0][i]
    doc = res['documents'][0][i]
    print(f"Dist: {dist:.2f} | Rank: {i+1} | Text: {doc[:50]}")
