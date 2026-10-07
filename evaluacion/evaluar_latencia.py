"""
Medición reproducible de latencia del pipeline conversacional (modo local).

Para cada pregunta del banco:
  1. Se sintetiza la pregunta hablada con edge-tts (simula la voz del estudiante).
  2. STT: se envía el audio a Groq Whisper-large-v3 (mismo modelo que /api/stt) y
     se calcula el WER contra el texto original.
  3. RAG + LLM: se invoca la función de producción api.generar_respuesta(), que
     devuelve las latencias internas (rag_ms, ttfb_ms del primer fragmento, llm_ms).
  4. TTS: se envía la respuesta a ElevenLabs (mismo endpoint, voz y modelo que /api/tts)
     y se mide el tiempo hasta el primer byte de audio (TTFB) y el tiempo total.

Latencia percibida estimada = STT + respuesta completa (RAG + LLM) + TTFB del TTS
(momento en que el avatar empieza a hablar; el frontend sintetiza la voz al completar
el texto). Las preguntas fuera de dominio verifican la restricción de dominio (sin TTS).

Uso (desde la raíz del proyecto):
    .venv/bin/python evaluacion/evaluar_latencia.py [N_PREGUNTAS_DOMINIO]
"""
import asyncio
import csv
import io
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
import edge_tts
import httpx
from openai import OpenAI
from sentence_transformers import SentenceTransformer

import api
from rag_manager import COLLECTION_NAME, EMBEDDING_MODEL, Recuperador, cargar_reranker

BASE = os.path.dirname(os.path.abspath(__file__))
VOZ_ESTUDIANTE = "es-EC-LuisNeural"
MODELO_TTS = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")  # mismo valor por defecto que /api/tts
PATRONES_RECHAZO = [r"solo tengo informaci", r"no puedo cambiar mi rol", r"no encontr[eé]"]


def normalizar(texto):
    texto = texto.lower()
    texto = re.sub(r"[¿?¡!.,;:\"']", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def wer(referencia, hipotesis):
    r, h = normalizar(referencia).split(), normalizar(hipotesis).split()
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r)][len(h)] / max(len(r), 1)


async def sintetizar_pregunta(texto):
    audio = io.BytesIO()
    async for chunk in edge_tts.Communicate(texto, VOZ_ESTUDIANTE).stream():
        if chunk["type"] == "audio":
            audio.write(chunk["data"])
    return audio.getvalue()


def transcribir(cliente_stt, audio):
    t0 = time.perf_counter()
    res = cliente_stt.audio.transcriptions.create(model="whisper-large-v3",
                                                  file=("pregunta.mp3", audio), language="es")
    return res.text, (time.perf_counter() - t0) * 1000


async def sintetizar_respuesta(texto):
    """Réplica de /api/tts: mismo endpoint, voz y modelo de ElevenLabs."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{os.getenv('ELEVENLABS_VOICE_ID', 'ewn5JTa3lNPY8QVuZJi6')}/stream"
    headers = {"Accept": "audio/mpeg", "Content-Type": "application/json",
               "xi-api-key": os.getenv("ELEVENLABS_API_KEY")}
    payload = {"text": texto, "model_id": MODELO_TTS,
               "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    t0 = time.perf_counter()
    ttfb, total_bytes = None, 0
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=1024):
                if ttfb is None:
                    ttfb = (time.perf_counter() - t0) * 1000
                total_bytes += len(chunk)
    return ttfb, (time.perf_counter() - t0) * 1000, total_bytes


def resumen(valores):
    v = sorted(valores)
    return {"n": len(v), "media": round(statistics.mean(v), 1), "desv_est": round(statistics.stdev(v), 1),
            "mediana": round(statistics.median(v), 1), "min": round(v[0], 1), "max": round(v[-1], 1),
            "p95": round(v[int(round(0.95 * (len(v) - 1)))], 1),
            "ic95_media": round(1.96 * statistics.stdev(v) / len(v) ** 0.5, 1)}


async def responder(texto):
    async for tipo, valor in api.generar_respuesta(texto, None):
        if tipo == "fin":
            return valor


async def main():
    n_dominio = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    banco = json.load(open(os.path.join(BASE, "banco_preguntas.json"), encoding="utf-8"))

    # Inicialización equivalente al startup de api.py
    api.embedder = SentenceTransformer(EMBEDDING_MODEL)
    api.chroma_collection = chromadb.PersistentClient(path="./chroma_db").get_collection(COLLECTION_NAME)
    api.recuperador = Recuperador(api.embedder, api.chroma_collection, cargar_reranker())
    {"ollama": api.precargar_ollama, "nvidia": api.init_nvidia, "groq": api.init_groq,
     "openwebui": api.init_openwebui, "siliconflow": api.init_siliconflow}[api.AI_PROVIDER]()
    cliente_stt = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
    modelo_llm = api.nombre_modelo_llm()

    # Calentamiento (no se registra): carga del modelo y primera conexión TLS
    await responder("Hola")

    filas = []
    preguntas = [(p, "dominio") for p in banco["dominio"][:n_dominio]] + \
                [(p, "fuera_de_dominio") for p in banco["fuera_de_dominio"]]
    for item, tipo in preguntas:
        audio = await sintetizar_pregunta(item["pregunta"])
        texto, stt_ms = await asyncio.to_thread(transcribir, cliente_stt, audio)
        t0 = time.perf_counter()
        r = await responder(texto)  # cada consulta es una sesión nueva (sin historial)
        respuesta_ms = (time.perf_counter() - t0) * 1000
        t = r.get("timings", {})
        fila = {"id": item["id"], "tipo": tipo, "pregunta": item["pregunta"], "transcripcion": texto,
                "wer": round(wer(item["pregunta"], texto), 4), "stt_ms": round(stt_ms, 1),
                "rag_ms": t.get("rag_ms", 0.0), "ttfb_texto_ms": t.get("ttfb_ms", 0.0),
                "llm_ms": t.get("llm_ms", 0.0), "respuesta_completa_ms": round(respuesta_ms, 1),
                "respuesta": r["reply"], "caracteres_respuesta": len(r["reply"])}
        if tipo == "dominio":
            ttfb, tts_total, _ = await sintetizar_respuesta(r["reply"])
            fila.update({"tts_ttfb_ms": round(ttfb, 1), "tts_total_ms": round(tts_total, 1),
                         "latencia_percibida_ms": round(stt_ms + respuesta_ms + ttfb, 1)})
        else:
            fila["rechazo_correcto"] = int(any(re.search(p, r["reply"].lower()) for p in PATRONES_RECHAZO))
        filas.append(fila)
        print(f"{item['id']}: stt={fila['stt_ms']:.0f} rag={fila['rag_ms']:.0f} llm={fila['llm_ms']:.0f} "
              f"tts={fila.get('tts_ttfb_ms', 0):.0f} -> {r['reply'][:70]!r}")

    dom = [f for f in filas if f["tipo"] == "dominio"]
    fuera = [f for f in filas if f["tipo"] == "fuera_de_dominio"]
    res = {
        "modo": "local", "proveedor_llm": api.AI_PROVIDER, "modelo_llm": modelo_llm,
        "stt": "groq/whisper-large-v3", "tts": f"elevenlabs/{MODELO_TTS}",
        "fecha": time.strftime("%Y-%m-%d %H:%M"),
        "stt_ms": resumen([f["stt_ms"] for f in filas]),
        # Solo preguntas del dominio: el filtro de jailbreak responde sin RAG ni LLM (0 ms)
        "rag_ms": resumen([f["rag_ms"] for f in dom]),
        "ttfb_texto_ms": resumen([f["ttfb_texto_ms"] for f in dom]),
        "llm_ms": resumen([f["llm_ms"] for f in dom]),
        "respuesta_completa_ms": resumen([f["respuesta_completa_ms"] for f in dom]),
        "tts_ttfb_ms": resumen([f["tts_ttfb_ms"] for f in dom]),
        "tts_total_ms": resumen([f["tts_total_ms"] for f in dom]),
        "latencia_percibida_ms": resumen([f["latencia_percibida_ms"] for f in dom]),
        "wer_medio": round(statistics.mean(f["wer"] for f in filas), 4),
        "transcripciones_exactas": sum(f["wer"] == 0 for f in filas),
        "n_transcripciones": len(filas),
        "rechazos_correctos_fuera_dominio": sum(f["rechazo_correcto"] for f in fuera),
        "n_fuera_dominio": len(fuera),
    }
    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    campos = sorted({k for f in filas for k in f}, key=lambda k: list(filas[0]).index(k) if k in filas[0] else 99)
    with open(os.path.join(BASE, "resultados", "latencia_detalle.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    with open(os.path.join(BASE, "resultados", "latencia_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
