"""
Genera las respuestas del sistema para la evaluación manual de exactitud.

Usa la función de producción api.generar_respuesta() (RAG híbrido + LLM configurado
en .env) sin historial: cada pregunta es una consulta independiente. Se generan:
  - las 30 primeras preguntas del banco de desarrollo (mismas de la evaluación previa),
  - las 50 preguntas del banco de prueba reservado,
  - las 10 preguntas fuera de dominio (se verifica el rechazo automáticamente).

La columna "clasificacion" (Correcta, Parcial, Incorrecta, No responde) se completa
manualmente contrastando cada respuesta con el documento fuente.

Uso (desde la raíz del proyecto):
    .venv/bin/python evaluacion/generar_respuestas.py
"""
import asyncio
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from sentence_transformers import SentenceTransformer

import api
from rag_manager import COLLECTION_NAME, EMBEDDING_MODEL, Recuperador, cargar_reranker

BASE = os.path.dirname(os.path.abspath(__file__))
PATRONES_RECHAZO = [r"solo tengo informaci", r"no puedo cambiar mi rol", r"no encontr[eé]"]


async def responder(pregunta):
    async for tipo, valor in api.generar_respuesta(pregunta, None):
        if tipo == "fin":
            return valor["reply"]


async def main():
    api.embedder = SentenceTransformer(EMBEDDING_MODEL)
    api.chroma_collection = chromadb.PersistentClient(path="./chroma_db").get_collection(COLLECTION_NAME)
    api.recuperador = Recuperador(api.embedder, api.chroma_collection, cargar_reranker())
    if api.AI_PROVIDER == "ollama":
        api.precargar_ollama()

    desarrollo = json.load(open(os.path.join(BASE, "banco_preguntas.json"), encoding="utf-8"))
    prueba = json.load(open(os.path.join(BASE, "banco_prueba.json"), encoding="utf-8"))
    preguntas = [("desarrollo", p) for p in desarrollo["dominio"][:30]] + \
                [("prueba", p) for p in prueba["dominio"]] + \
                [("fuera_de_dominio", p) for p in desarrollo["fuera_de_dominio"]]

    filas = []
    for banco, item in preguntas:
        respuesta = await responder(item["pregunta"])
        fila = {"banco": banco, "id": item["id"], "pregunta": item["pregunta"], "respuesta": respuesta,
                "clasificacion": "", "justificacion": ""}
        if banco == "fuera_de_dominio":
            rechazo = any(re.search(p, respuesta.lower()) for p in PATRONES_RECHAZO)
            fila["clasificacion"] = "Rechazo correcto" if rechazo else "No rechazada"
        filas.append(fila)
        print(f"{item['id']}: {respuesta}")

    salida = os.path.join(BASE, "resultados", f"respuestas_{api.AI_PROVIDER}.csv")
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"Guardado en {salida}")


if __name__ == "__main__":
    asyncio.run(main())
