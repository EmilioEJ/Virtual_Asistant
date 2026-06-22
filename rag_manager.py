import os
import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
import shutil
import time
import asyncio

# Variables globales para el progreso
rag_status = {
    "is_processing": False,
    "logs": [],
    "progress_percent": 0,
    "docs_loaded": 0
}

def add_log(msg: str):
    print(msg)
    rag_status["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

async def process_pdfs_async(file_paths: list[str]):
    global rag_status
    rag_status["is_processing"] = True
    rag_status["logs"] = []
    rag_status["progress_percent"] = 0
    
    try:
        # 1. Limpiar la base de datos anterior
        add_log("Iniciando reconstrucción de la base de conocimiento...")
        db_path = "./chroma_db"
        
        # Eliminar base de datos por completo para forzar un reemplazo limpio
        if os.path.exists(db_path):
            add_log("Borrando conocimiento anterior...")
            # En Windows esto puede fallar si SQLite tiene locks, pero en Linux funciona bien
            shutil.rmtree(db_path, ignore_errors=True)
            await asyncio.sleep(1) # Esperar a que el filesystem se limpie
            
        rag_status["progress_percent"] = 10
        
        # 2. Inicializar base nueva
        add_log("Inicializando nueva base de datos vectorial ChromaDB...")
        chroma_client = chromadb.PersistentClient(path=db_path)
        collection = chroma_client.create_collection(name="carrera_ti_indoamerica_collection")
        
        rag_status["progress_percent"] = 20

        # 3. Cargar el modelo matemático (Lento la primera vez)
        add_log("Cargando motor de Inteligencia Artificial (SentenceTransformer)...")
        # Ejecutar carga sincrónica pesada en thread
        embedder = await asyncio.to_thread(SentenceTransformer, "all-MiniLM-L6-v2")
        
        rag_status["progress_percent"] = 40
        
        all_chunks = []
        
        # 4. Procesar cada archivo PDF
        total_files = len(file_paths)
        for idx, path in enumerate(file_paths):
            filename = os.path.basename(path)
            add_log(f"📄 Procesando documento ({idx+1}/{total_files}): {filename}")
            
            # Extraer Markdown
            md_text = await asyncio.to_thread(pymupdf4llm.to_markdown, path)
            add_log(f"✅ {filename} leído exitosamente ({len(md_text)} caracteres).")
            
            # Dividir en chunks
            add_log(f"✂️ Dividiendo {filename} en fragmentos lógicos...")
            text_splitter = MarkdownTextSplitter(chunk_size=2500, chunk_overlap=400)
            chunks = text_splitter.split_text(md_text)
            
            # Agregar metadatos a cada chunk
            for i, chunk in enumerate(chunks):
                all_chunks.append({
                    "id": f"{filename}_chunk_{i}",
                    "text": chunk,
                    "metadata": {"source": filename}
                })
                
            progress_step = 40 + int(((idx + 1) / total_files) * 30)
            rag_status["progress_percent"] = progress_step
            
        add_log(f"Se generaron {len(all_chunks)} fragmentos en total a partir de {total_files} documentos.")
        rag_status["progress_percent"] = 75
        
        if len(all_chunks) > 0:
            # 5. Calcular Vectores Matemáticos e Insertar en DB
            add_log("Calculando vectores matemáticos (Embeddings) para cada fragmento...")
            
            texts = [c["text"] for c in all_chunks]
            ids = [c["id"] for c in all_chunks]
            metadatas = [c["metadata"] for c in all_chunks]
            
            # Encode toma tiempo, lo mandamos a un thread
            embeddings = await asyncio.to_thread(embedder.encode, texts)
            embeddings_list = embeddings.tolist()
            
            rag_status["progress_percent"] = 90
            
            add_log("Guardando fragmentos vectorizados en la base de datos...")
            collection.add(
                documents=texts,
                embeddings=embeddings_list,
                metadatas=metadatas,
                ids=ids
            )
            
            rag_status["docs_loaded"] = total_files
            add_log("🎉 ¡Proceso RAG completado con éxito! El asistente ya tiene la nueva información.")
        else:
            add_log("⚠️ No se extrajo ningún texto de los PDFs.")
            
        rag_status["progress_percent"] = 100
        rag_status["is_processing"] = False
        
    except Exception as e:
        add_log(f"❌ ERROR FATAL: {str(e)}")
        rag_status["is_processing"] = False
        
def get_rag_status():
    return rag_status
