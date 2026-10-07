import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
import os 
from rag_manager import COLLECTION_NAME, COLLECTION_METADATA, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP

def extract_pdf_text(path: str) -> str:
    print(f"Extrayendo texto y tablas en formato Markdown del PDF: {path}...")
    # pymupdf4llm convierte automáticamente el PDF y las tablas en Markdown perfecto
    md_text = pymupdf4llm.to_markdown(path)
    return md_text

def build_index():
    pdf_path = "Investigación Carrera TI Indoamérica Quito.pdf"
    if not os.path.exists(pdf_path):
        print(f"❌ No se encontró el archivo: {pdf_path}")
        return

    text = extract_pdf_text(pdf_path)
    print(f"Texto extraido: {len(text)} caracteres.")

    # Chunking: Dividir el texto en fragmentos (Aumentado para que quepan tablas completas)
    print("Dividiendo documento Markdown en fragmentos (chunks)...")
    text_splitter = MarkdownTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )
    chunks = text_splitter.split_text(text)
    print(f"Se generaron {len(chunks)} fragmentos.")

    # Cargar modelo de Embeddings
    print("Cargando modelo de Embeddings (sentence-transformers)...")
    # Usamos paraphrase-multilingual-MiniLM-L12-v2, optimizado para español y más de 50 idiomas
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    # Inicializar ChromaDB
    print("💾 Inicializando base de datos vectorial ChromaDB...")
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    
    # Crear o recrear la colección
    collection_name = COLLECTION_NAME
    try:
        chroma_client.delete_collection(name=collection_name)
    except:
        pass # Ignorar si no existe
    
    collection = chroma_client.create_collection(name=collection_name, metadata=COLLECTION_METADATA)

    # Convertir a embeddings y guardar
    print("Calculando vectores y guardando en la base de datos... (esto puede tardar unos segundos)")
    embeddings = embedder.encode(chunks).tolist()
    
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    
    collection.add(
        documents=chunks,
        embeddings=embeddings,
        metadatas=[{"source": os.path.basename(pdf_path)} for _ in chunks],
        ids=ids
    )

    print("🎉 ¡Base de datos RAG construida exitosamente en ./chroma_db!")

if __name__ == "__main__":
    build_index()
