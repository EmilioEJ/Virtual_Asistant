import io
import os
import asyncio
import cv2
import numpy as np
import base64
import edge_tts
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import chromadb
from typing import List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, BackgroundTasks, Request, Response, Depends
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import sqlite3
import uuid
from init_db import init_db, hash_password

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
    mode: str = "chat" # Puede ser "chat" o "conversational"

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
    # Inicializar la base de datos de usuarios
    try:
        init_db()
    except Exception as e:
        print(f"Error inicializando base de datos de usuarios: {e}")

    global embedder, chroma_collection
    try:
        # Inicializar base de datos vectorial (RAG)
        try:
            print("🧠 Inicializando RAG (Cargando Embedder y ChromaDB)...")
            embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
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
        # (Ya no se usa tarea local, se procesa en el WebSocket)
    except Exception as e:
        print(f"❌ Error iniciando el backend: {e}")

# ============================================================
# Auth (Login/Sessiones)
# ============================================================
def get_current_user(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM sessions WHERE session_token = ?", (session_token,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    return row[0]

def verify_page_auth(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token:
        return False
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM sessions WHERE session_token = ?", (session_token,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
async def api_login(data: LoginRequest, response: Response):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (data.username,))
    row = cursor.fetchone()
    
    if not row or row[0] != hash_password(data.password):
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
        
    session_token = str(uuid.uuid4())
    cursor.execute("INSERT INTO sessions (session_token, username) VALUES (?, ?)", (session_token, data.username))
    conn.commit()
    conn.close()
    
    response.set_cookie(key="session_token", value=session_token, httponly=True)
    return {"message": "Login exitoso"}

@app.post("/api/logout")
async def api_logout(response: Response):
    response.delete_cookie("session_token")
    return {"message": "Logout exitoso"}

# ============================================================
# Endpoint de Chat
# ============================================================

@app.post("/api/chat")
async def chat_endpoint(data: MessageInput, user: str = Depends(get_current_user)):
    try:
        if AI_PROVIDER in ("siliconflow", "groq", "openwebui"):
            return await chat_siliconflow(data.message, data.mode)
        else:
            return await chat_gemini(data.message, data.mode)
    except Exception as e:
        error_msg = str(e).lower()
        if "quota" in error_msg or "429" in error_msg or "rate" in error_msg:
            return {"reply": "(Sistema bloqueado por Rate Limit, espere un momento por favor)."}
        if "already being processed" in error_msg:
            return {"reply": "(Un momento, sigo procesando mi respuesta anterior)."}
        raise HTTPException(status_code=500, detail="Error de IA: " + str(e))

# ============================================================
# Endpoint de Voz a Texto (Whisper STT)
# ============================================================
@app.post("/api/stt")
async def stt_endpoint(audio: UploadFile = File(...), user: str = Depends(get_current_user)):
    from openai import OpenAI
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(status_code=500, detail="Falta GROQ_API_KEY en .env")

    try:
        # Groq Audio API usa el cliente de OpenAI compatible
        stt_client = OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1"
        )
        
        # Leemos el archivo enviado por el navegador
        audio_bytes = await audio.read()
        
        # Whisper requiere un nombre de archivo con extensión reconocida
        transcription = await asyncio.to_thread(
            stt_client.audio.transcriptions.create,
            model="whisper-large-v3",
            file=(audio.filename or "audio.webm", audio_bytes),
            language="es"
        )
        return {"text": transcription.text}
    except Exception as e:
        print(f"Error en STT Whisper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Endpoints de Panel de Administración RAG
# ============================================================
from rag_manager import process_pdfs_async, get_rag_status

def _reload_rag_collection():
    global chroma_collection
    try:
        print("🔄 Recargando colección ChromaDB en memoria...")
        chroma_client = chromadb.PersistentClient(path="./chroma_db")
        chroma_collection = chroma_client.get_collection(name="carrera_ti_indoamerica_collection")
        print("✅ Colección recargada exitosamente.")
    except Exception as e:
        print(f"⚠️ Error al recargar colección ChromaDB: {e}")

async def background_process_docs(file_paths: List[str]):
    # Ejecuta el procesamiento de rag_manager
    await process_pdfs_async(file_paths)
    # Una vez terminado, refrescamos la conexión en memoria de la API
    _reload_rag_collection()

@app.post("/api/admin/upload_docs")
async def upload_docs(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...), user: str = Depends(get_current_user)):
    # Rechazar si ya hay un proceso en curso
    status = get_rag_status()
    if status.get("is_processing"):
        raise HTTPException(status_code=400, detail="Ya hay un procesamiento RAG en curso.")

    # Guardar archivos temporalmente
    os.makedirs("docs_temp", exist_ok=True)
    file_paths = []
    
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            continue
        file_path = os.path.join("docs_temp", file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
        file_paths.append(file_path)

    if not file_paths:
        raise HTTPException(status_code=400, detail="No se enviaron archivos PDF válidos.")

    # Iniciar procesamiento en background
    background_tasks.add_task(background_process_docs, file_paths)
    return {"message": f"Procesamiento de {len(file_paths)} archivos iniciado en background."}

@app.get("/api/admin/rag_status")
async def rag_status_endpoint(user: str = Depends(get_current_user)):
    status = get_rag_status()
    # Retorna el estado global del progreso
    # Calculamos también el número de documentos actuales en DB
    global chroma_collection
    docs_in_db = chroma_collection.count() if chroma_collection else 0
    return {
        "is_processing": status["is_processing"],
        "progress_percent": status["progress_percent"],
        "logs": status["logs"][-15:], # Últimos 15 logs
        "docs_in_db": docs_in_db
    }

async def chat_gemini(message: str, mode: str):
    global chat_session, gemini_lock
    if not chat_session:
        raise HTTPException(status_code=500, detail="El modelo Gemini no está inicializado.")
    
    prompt = message
    # Aplicar la misma regla de brevedad para ambos modos
    prompt += "\n\n(Regla del sistema para este mensaje: Responde de manera MUY BREVE, concisa y directa. No uses párrafos largos ni listas detalladas)."

    async with gemini_lock:
        response = await asyncio.to_thread(chat_session.send_message, prompt)
    return {"reply": response.text}

async def chat_siliconflow(message: str, mode: str):
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
        import re
        search_query = message.lower()
        
        # Normalización semántica para ayudar al modelo MiniLM
        reemplazos = {
            r'\b1er\b': 'primer', r'\b1ro\b': 'primer', r'\b1ero\b': 'primer',
            r'\b2do\b': 'segundo', r'\b2da\b': 'segunda',
            r'\b3er\b': 'tercer', r'\b3ro\b': 'tercero',
            r'\b4to\b': 'cuarto', r'\b5to\b': 'quinto', r'\b6to\b': 'sexto',
            r'\b7mo\b': 'séptimo', r'\b8vo\b': 'octavo',
            r'\bsemestre\b': 'nivel', r'\bsemestres\b': 'niveles',
            r'\bmateria\b': 'asignatura', r'\bmaterias\b': 'asignaturas'
        }
        for patron, reemplazo in reemplazos.items():
            search_query = re.sub(patron, reemplazo, search_query)
        
        query_embedding = embedder.encode(search_query).tolist()
        results = chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=12 # Aumentado a 12 para asegurar atrapar la malla completa
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

    # Aplicar el mismo sistema de respuestas breves para el chat y conversacional
    user_message_with_context += "\n\n(Regla del sistema: Tus respuestas DEBEN SER MUY CORTAS, concisas y directas. No uses párrafos largos ni listas detalladas. Mantén una charla natural y fluida.)"

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

import httpx

@app.post("/api/tts")
async def tts_endpoint(data: MessageInput):
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
    if not elevenlabs_api_key:
        raise HTTPException(status_code=500, detail="Falta ELEVENLABS_API_KEY en .env")

    # Voz: Ana Sofía (Voz Joven, Acento Mexicano, Tono Casual y Dulce)
    voice_id = "ewn5JTa3lNPY8QVuZJi6"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": elevenlabs_api_key
    }
    
    payload = {
        "text": data.message,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    async def stream_audio():
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error_detail = await response.aread()
                    print(f"Error ElevenLabs: {error_detail}")
                    return
                async for chunk in response.aiter_bytes(chunk_size=1024):
                    yield chunk

    return StreamingResponse(stream_audio(), media_type="audio/mpeg")

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

# Cargar clasificador de rostros globalmente
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    person_present = False
    present_frames = 0
    missing_frames = 0
    
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("data:image"):
                base64_data = data.split(",")[1]
                img_data = base64.b64decode(base64_data)
                np_arr = np.frombuffer(img_data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
                    
                    if len(faces) > 0:
                        present_frames += 1
                        missing_frames = 0
                        if present_frames > 1 and not person_present:
                            person_present = True
                            print("--> OpenCV: ¡Rostro Detectado desde WebSocket!")
                            await websocket.send_text("person_arrived")
                    else:
                        present_frames = 0
                        missing_frames += 1
                        if missing_frames > 3 and person_present:
                            person_present = False
                            print("--> OpenCV: ¡Persona retirada de cámara WebSocket!")
                            await websocket.send_text("person_left")
    except WebSocketDisconnect:
        ws_clients.remove(websocket)
    except Exception as e:
        print(f"Error procesando frame base64 WebSocket: {e}")
        try:
            ws_clients.remove(websocket)
        except:
            pass

# ============================================================
# Frontend estático y Rutas de Página
# ============================================================

@app.get("/")
async def root_page(request: Request):
    if not verify_page_auth(request):
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")

@app.get("/admin.html")
async def admin_html_page(request: Request):
    if not verify_page_auth(request):
        return RedirectResponse(url="/login")
    return FileResponse("static/admin.html")

@app.get("/login")
async def login_html_page(request: Request):
    # Si ya está autenticado, redirigir a inicio
    if verify_page_auth(request):
        return RedirectResponse(url="/")
    return FileResponse("static/login.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
