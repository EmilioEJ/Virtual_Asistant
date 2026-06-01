import io
import os
import asyncio
import cv2
import edge_tts
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import chromadb
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ============================================================
# Configuración global
# ============================================================
chat_session = None      # Solo se usa con Gemini
openai_client = None     # Solo se usa con SiliconFlow
openai_history = []      # Historial de mensajes para SiliconFlow (OpenAI-style)
ws_clients = set()
gemini_lock = asyncio.Lock()

embedder = None
chroma_collection = None

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()  # "gemini" | "siliconflow" | "groq" | "openwebui"

SYSTEM_INSTRUCTION = (
    "Eres Aria, el Asistente Virtual Oficial de la carrera universitaria de Tecnologías de la Información. "
    "Responde de forma concisa, amigable, clara y entusiasta. Si te presentas, di que te llamas Aria. "
    "Basate SÓLO en el documento proporcionado. "
    "IMPORTANTE: NUNCA uses emojis ni emoticonos en tus respuestas bajo ninguna circunstancia. Solo texto plano."
    "\n\nREGLAS ESTRICTAS QUE DEBES SEGUIR SIN EXCEPCIÓN:\n"
    "1. SOLO puedes responder preguntas cuya respuesta esté explícita o implícitamente contenida en el documento proporcionado. "
    "2. Si la pregunta NO está relacionada con el contenido del documento (por ejemplo: programación general, ciencia, historia, cocina, humor, cultura popular, otros temas ajenos), "
    "   responde SIEMPRE con exactamente: 'Solo puedo responder preguntas relacionadas con el documento de la carrera. ¿Tienes alguna pregunta sobre la carrera?' "
    "3. NUNCA generes código fuente de ningún lenguaje de programación. "
    "4. NUNCA inventes, supongas ni inferas información que no esté literalmente presente en el documento. "
    "5. NUNCA uses emojis ni emoticonos. Solo texto plano. "
    "6. NUNCA respondas preguntas sobre otros temas aunque el usuario insista, sea amable o formule la pregunta de manera indirecta. "
    "7. Si no encuentras la respuesta en el documento, di: 'No encontré esa información en el documento de la carrera.' \n"
    "8. MUY IMPORTANTE: En el contexto de esta carrera, las palabras 'Semestre' y 'Nivel' son sinónimos exactos. Si el usuario pregunta por 'semestres', busca y responde usando la información de los 'niveles'. "
    "Recuerda: Tu conocimiento está limitado estrictamente al documento oficial de la carrera universitaria. Cualquier otra solicitud debe ser rechazada cortésmente con las frases indicadas."
)

class MessageInput(BaseModel):
    message: str

# ============================================================
# Utilidades comunes
# ============================================================

def extract_pdf_text(path: str) -> str:
    """Extrae todo el texto de un PDF usando PyMuPDF (para SiliconFlow/DeepSeek)."""
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text.strip()

# ============================================================
# Inicialización Gemini
# ============================================================

def init_gemini():
    global chat_session
    import google.generativeai as genai
    import time

    API_KEY = os.getenv("GEMINI_API_KEY")
    if not API_KEY or API_KEY == "TU_API_KEY_AQUI":
        print("❌ Por favor configura GEMINI_API_KEY en el .env")
        return

    genai.configure(api_key=API_KEY)

    def upload_and_wait(path):
        print(f"Subiendo {path} a Gemini...")
        file = genai.upload_file(path, mime_type="application/pdf")
        while file.state.name == "PROCESSING":
            time.sleep(2)
            file = genai.get_file(file.name)
        if file.state.name != "ACTIVE":
            raise Exception("Error al procesar el archivo en Gemini.")
        return file

    pdf_file = upload_and_wait("Investigación Carrera TI Indoamérica Quito.pdf")
    model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")
    generation_config = genai.types.GenerationConfig(
        temperature=0.1,       # Baja temperatura para reducir alucinaciones
        top_p=0.85,
        top_k=20,
    )
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=generation_config
    )
    chat_session = model.start_chat(
        history=[
            {"role": "user",  "parts": [pdf_file, "Revisa este documento sobre mi carrera, te haré preguntas."]},
            {"role": "model", "parts": ["¡Entendido! He revisado el documento. ¡Pregúntame lo que necesites!"]}
        ]
    )
    print(f"✅ Gemini ({model_name}) inicializado correctamente.")

# ============================================================
# Inicialización SiliconFlow (DeepSeek — API compatible con OpenAI)
# ============================================================

def _init_openai_compatible(api_key: str, base_url: str, model_name: str, provider_name: str):
    """Inicializa cualquier proveedor con API compatible con OpenAI (SiliconFlow, Groq, etc.)"""
    global openai_client, openai_history
    from openai import OpenAI

    if not api_key:
        print(f"❌ Por favor configura la API key de {provider_name} en el .env")
        return

    openai_client = OpenAI(api_key=api_key, base_url=base_url)

    openai_history = [
        {"role": "system", "content": SYSTEM_INSTRUCTION}
    ]
    print(f"✅ {provider_name} ({model_name}) inicializado.")

def init_siliconflow():
    _init_openai_compatible(
        api_key=os.getenv("SILICONFLOW_API_KEY"),
        base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        model_name=os.getenv("SILICONFLOW_MODEL_NAME", "deepseek-ai/DeepSeek-V3"),
        provider_name="SiliconFlow"
    )

def init_groq():
    _init_openai_compatible(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        model_name=os.getenv("GROQ_MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct"),
        provider_name="Groq"
    )

def init_openwebui():
    _init_openai_compatible(
        api_key=os.getenv("OPENWEBUI_API_KEY"),
        base_url=os.getenv("OPENWEBUI_BASE_URL", "http://63.141.255.7:3000/api"),
        model_name=os.getenv("OPENWEBUI_MODEL_NAME", "qwen2.5-coder:14b"),
        provider_name="Open WebUI"
    )

# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
def startup_event():
    global embedder, chroma_collection
    try:
        # Inicializar base de datos vectorial (RAG)
        try:
            print("🧠 Inicializando RAG (Cargando Embedder y ChromaDB)...")
            embedder = SentenceTransformer("all-MiniLM-L6-v2")
            chroma_client = chromadb.PersistentClient(path="./chroma_db")
            chroma_collection = chroma_client.get_collection(name="carrera_ti_indoamerica_collection")
            print(f"✅ RAG Inicializado. Fragmentos cargados: {chroma_collection.count()}")
        except Exception as rag_e:
            print(f"⚠️ No se pudo iniciar RAG. Asegúrate de ejecutar build_rag_index.py primero. Error: {rag_e}")

        if AI_PROVIDER == "siliconflow":
            init_siliconflow()
        elif AI_PROVIDER == "groq":
            init_groq()
        elif AI_PROVIDER == "openwebui":
            init_openwebui()
        else:
            init_gemini()

        # Iniciar visión artificial en segundo plano
        asyncio.create_task(vision_worker_task())
    except Exception as e:
        print(f"❌ Error iniciando el backend: {e}")

# ============================================================
# Endpoint de Chat
# ============================================================

@app.post("/api/chat")
async def chat_endpoint(data: MessageInput):
    try:
        if AI_PROVIDER in ("siliconflow", "groq", "openwebui"):
            return await chat_siliconflow(data.message)
        else:
            return await chat_gemini(data.message)
    except Exception as e:
        error_msg = str(e).lower()
        if "quota" in error_msg or "429" in error_msg or "rate" in error_msg:
            return {"reply": "(Sistema bloqueado por Rate Limit, espere un momento por favor)."}
        if "already being processed" in error_msg:
            return {"reply": "(Un momento, sigo procesando mi respuesta anterior)."}
        raise HTTPException(status_code=500, detail="Error de IA: " + str(e))

async def chat_gemini(message: str):
    global chat_session, gemini_lock
    if not chat_session:
        raise HTTPException(status_code=500, detail="El modelo Gemini no está inicializado.")
    async with gemini_lock:
        response = await asyncio.to_thread(chat_session.send_message, message)
    return {"reply": response.text}

async def chat_siliconflow(message: str):
    global openai_client, openai_history, embedder, chroma_collection
    if not openai_client:
        raise HTTPException(status_code=500, detail="El cliente no está inicializado.")

    if AI_PROVIDER == "groq":
        model_name = os.getenv("GROQ_MODEL_NAME", "meta-llama/llama-4-scout-17b-16e-instruct")
    elif AI_PROVIDER == "openwebui":
        model_name = os.getenv("OPENWEBUI_MODEL_NAME", "qwen2.5-coder:14b")
    else:
        model_name = os.getenv("SILICONFLOW_MODEL_NAME", "deepseek-ai/DeepSeek-V3")
        
    # --- PROCESO DE RECUPERACIÓN RAG CON QUERY EXPANSION ---
    context_text = ""
    if embedder and chroma_collection:
        # Enriquecer la búsqueda (Query Expansion) para sortear problemas de sinónimos
        search_query = message.lower()
        if "semestre" in search_query or "nivel" in search_query:
            search_query += " niveles malla curricular semestres tabla"
        if "materia" in search_query or "asignatura" in search_query:
            search_query += " asignaturas materias plan de estudios malla curricular tabla"

        query_embedding = embedder.encode(search_query).tolist()
        results = chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=6 # Aumentamos a 6 fragmentos (casi 15,000 caracteres) para garantizar atrapar toda la tabla
        )
        if results['documents'] and len(results['documents'][0]) > 0:
            context_text = "\n\n--- INFORMACIÓN RECUPERADA DEL DOCUMENTO OFICIAL ---\n"
            for idx, doc in enumerate(results['documents'][0]):
                context_text += f"[Contexto {idx+1}]: {doc}\n"
            context_text += "----------------------------------------------------\n"
            context_text += "Utiliza la información anterior para responder a la pregunta del usuario. Si la información no responde la pregunta, indícalo educadamente."
            print(f"🔍 RAG: Recuperados {len(results['documents'][0])} fragmentos para la pregunta.")

    # Clonamos el historial para enviar el contexto sin ensuciar el historial real
    temp_messages = list(openai_history)
    user_message_with_context = message
    if context_text:
        user_message_with_context += context_text

    temp_messages.append({"role": "user", "content": user_message_with_context})

    response = await asyncio.to_thread(
        lambda: openai_client.chat.completions.create(
            model=model_name,
            messages=temp_messages,
            temperature=0.1,      # Baja temperatura para reducir alucinaciones
        )
    )
    reply = response.choices[0].message.content
    
    # Guardamos en el historial solo la conversación limpia
    openai_history.append({"role": "user", "content": message})
    openai_history.append({"role": "assistant", "content": reply})
    
    return {"reply": reply}

# ============================================================
# Endpoint TTS
# ============================================================

@app.post("/api/tts")
async def tts_endpoint(data: MessageInput):
    VOICE_MODEL = "es-MX-DaliaNeural"
    try:
        communicate = edge_tts.Communicate(data.message, VOICE_MODEL)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        buf = io.BytesIO(audio_data)
        buf.seek(0)
        return StreamingResponse(buf, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Debug Endpoints (Para diagnosticar problemas de RAG)
# ============================================================
@app.get("/debug/md")
async def debug_md():
    import pymupdf4llm
    import os
    pdf_path = "Investigación Carrera TI Indoamérica Quito.pdf"
    if not os.path.exists(pdf_path):
        return {"error": "PDF no encontrado"}
    md_text = pymupdf4llm.to_markdown(pdf_path)
    return {"text": md_text}

@app.get("/debug/rag")
async def debug_rag(q: str):
    global embedder, chroma_collection
    if not embedder or not chroma_collection:
        return {"error": "RAG no está inicializado"}
    query_embedding = embedder.encode(q).tolist()
    results = chroma_collection.query(query_embeddings=[query_embedding], n_results=4)
    return {"results": results}

# ============================================================
# WebSocket (Visión Artificial)
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.remove(websocket)

async def vision_worker_task():
    try:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        cap = cv2.VideoCapture(0)
        print("📷 OpenCV Encendido. Escaneando la cámara web...")

        person_present = False
        present_frames = 0
        missing_frames = 0

        while True:
            await asyncio.sleep(0.1)  # 10 FPS
            ret, frame = cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)

            if len(faces) > 0:
                present_frames += 1
                missing_frames = 0
                if present_frames > 5 and not person_present:
                    person_present = True
                    print("--> OpenCV: ¡Rostro Detectado!")
                    for client in ws_clients:
                        await client.send_text("person_arrived")
            else:
                present_frames = 0
                missing_frames += 1
                if missing_frames > 60 and person_present:
                    person_present = False
                    print("--> OpenCV: ¡Persona retirada de cámara!")
                    for client in ws_clients:
                        await client.send_text("person_left")
    except Exception as e:
        print("Error en OpenCV:", e)

# ============================================================
# Frontend estático
# ============================================================
app.mount("/", StaticFiles(directory="static", html=True), name="static")
