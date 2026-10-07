import os
import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
import shutil
import time
import asyncio
import re

import numpy as np
from rank_bm25 import BM25Okapi

# ============================================================
# Parámetros compartidos del motor RAG (api.py, build_rag_index.py y evaluación)
# ============================================================
COLLECTION_NAME = "carrera_ti_indoamerica_collection"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
# Distancia coseno explícita: ChromaDB usa L2 por defecto si no se indica.
COLLECTION_METADATA = {"hnsw:space": "cosine"}
# Fragmentos de 800/160 caracteres: mantienen la recuperación y reducen el prompt del LLM
CHUNK_SIZE = 800
CHUNK_OVERLAP = 160
RAG_TOP_K = 3  # Fragmentos inyectados en el prompt del LLM
# Recuperación híbrida: candidatos de cada buscador y cross-encoder multilingüe de reordenamiento
CANDIDATOS_RRF = 20
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Normalización semántica para ayudar al modelo MiniLM
_REEMPLAZOS = {
    r'\b1er\b': 'primer', r'\b1ro\b': 'primer', r'\b1ero\b': 'primer',
    r'\b2do\b': 'segundo', r'\b2da\b': 'segunda',
    r'\b3er\b': 'tercer', r'\b3ro\b': 'tercero',
    r'\b4to\b': 'cuarto', r'\b5to\b': 'quinto', r'\b6to\b': 'sexto',
    r'\b7mo\b': 'séptimo', r'\b8vo\b': 'octavo',
    r'\bsemestre\b': 'nivel', r'\bsemestres\b': 'niveles',
    r'\bmateria\b': 'asignatura', r'\bmaterias\b': 'asignaturas',
    r'\bbeca\b': 'beca ayuda economica', r'\bbecas\b': 'becas ayudas economicas'
}

def preparar_consulta(message: str) -> str:
    """Normaliza la consulta y aplica Query Expansion antes de vectorizarla."""
    search_query = message.lower()
    for patron, reemplazo in _REEMPLAZOS.items():
        search_query = re.sub(patron, reemplazo, search_query)
    # Mejorador de queries (Query Expansion) para sortear las debilidades del modelo de embeddings
    if "practica" in search_query or "práctica" in search_query:
        search_query += " Prácticas de Servicio Comunitario Sexto Nivel Prácticas Preprofesionales Séptimo Nivel"
    return search_query

_STOPWORDS = set("""a al algo algun alguna algunas alguno algunos ante antes como con contra cual cuales cuando de del desde
donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos fue fueron ha hay hasta la las
le les lo los mas me mi mis muy ni no nos o otra otras otro otros para pero por porque que quien se sea si sin sobre son su sus
tambien te tengo tiene tu tus un una unas uno unos y ya yo puedo hago veo cual cuanto cuanta cuantos cuantas""".split())

def tokenizar_bm25(texto: str) -> list[str]:
    """Tokenización para BM25: minúsculas, sin acentos, sin palabras vacías y con truncado a 6 letras (stemming ligero)."""
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", texto)
    return [t[:6] for t in tokens if t not in _STOPWORDS]

def fusion_rrf(*listas, k=60):
    """Fusión de rangos recíprocos (Reciprocal Rank Fusion) de varias listas ordenadas."""
    puntos = {}
    for lista in listas:
        for posicion, idx in enumerate(lista):
            puntos[idx] = puntos.get(idx, 0) + 1 / (k + posicion + 1)
    return sorted(puntos, key=puntos.get, reverse=True)

def cargar_reranker():
    """Carga el cross-encoder en GPU (FP16) si está disponible; si no, en CPU."""
    import torch
    from sentence_transformers import CrossEncoder
    if torch.cuda.is_available():
        return CrossEncoder(RERANKER_MODEL, max_length=512, device="cuda", model_kwargs={"torch_dtype": torch.float16})
    return CrossEncoder(RERANKER_MODEL, max_length=512, device="cpu")

class Recuperador:
    """Recuperación híbrida: búsqueda densa (MiniLM + ChromaDB) y léxica (BM25),
    fusionadas por RRF y reordenadas con un cross-encoder multilingüe."""

    def __init__(self, embedder, coleccion, reranker=None):
        self.embedder = embedder
        self.reranker = reranker
        self.recargar(coleccion)

    def recargar(self, coleccion):
        self.coleccion = coleccion
        datos = coleccion.get(include=["documents"])
        self.ids = datos["ids"]
        self.docs = datos["documents"]
        self.posicion = {id_: i for i, id_ in enumerate(self.ids)}
        self.bm25 = BM25Okapi([tokenizar_bm25(d) for d in self.docs]) if self.docs else None

    def buscar(self, pregunta: str, k: int = RAG_TOP_K) -> list[str]:
        if not self.docs:
            return []
        consulta = preparar_consulta(pregunta)
        n = min(CANDIDATOS_RRF, len(self.docs))
        vector = self.embedder.encode(consulta).tolist()
        res = self.coleccion.query(query_embeddings=[vector], n_results=n, include=[])
        densa = [self.posicion[i] for i in res["ids"][0]]
        lexica = list(np.argsort(-self.bm25.get_scores(tokenizar_bm25(consulta))))[:n]
        candidatos = fusion_rrf(densa, lexica)[:n]
        if self.reranker is not None:
            puntajes = self.reranker.predict([(pregunta, self.docs[j]) for j in candidatos])
            candidatos = [candidatos[i] for i in np.argsort(-puntajes)]
        return [self.docs[j] for j in candidatos[:k]]

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
        collection = chroma_client.create_collection(name=COLLECTION_NAME, metadata=COLLECTION_METADATA)
        
        rag_status["progress_percent"] = 20

        # 3. Cargar el modelo matemático (Lento la primera vez)
        add_log("Cargando motor de Inteligencia Artificial (SentenceTransformer)...")
        # Ejecutar carga sincrónica pesada en thread
        embedder = await asyncio.to_thread(SentenceTransformer, EMBEDDING_MODEL)
        
        rag_status["progress_percent"] = 40
        
        all_chunks = []
        
        # 4. Procesar cada archivo PDF
        total_files = len(file_paths)
        for idx, path in enumerate(file_paths):
            filename = os.path.basename(path)
            add_log(f"Procesando documento ({idx+1}/{total_files}): {filename}")
            
            # Extraer Markdown
            md_text = await asyncio.to_thread(pymupdf4llm.to_markdown, path)
            add_log(f"{filename} leido exitosamente ({len(md_text)} caracteres).")
            
            # Dividir en chunks
            add_log(f"Dividiendo {filename} en fragmentos logicos...")
            text_splitter = MarkdownTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
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
            add_log("No se extrajo ningun texto de los PDFs.")
            
        rag_status["progress_percent"] = 100
        rag_status["is_processing"] = False
        
    except Exception as e:
        add_log(f"❌ ERROR FATAL: {str(e)}")
        rag_status["is_processing"] = False
        
def get_rag_status():
    return rag_status
