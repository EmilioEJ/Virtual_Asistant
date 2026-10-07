"""
Comparación de estrategias de recuperación sobre el banco de DESARROLLO.

Las configuraciones se comparan solo con banco_preguntas.json; el banco de prueba
(banco_prueba.json) se reserva para la medición final de la configuración elegida.

Estrategias: densa (MiniLM), BM25, híbrida por fusión de rangos recíprocos (RRF)
y híbrida con reordenamiento mediante cross-encoder multilingüe.

Uso: .venv/bin/python evaluacion/experimento_recuperacion.py
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag_manager import EMBEDDING_MODEL, preparar_consulta, tokenizar_bm25
from rank_bm25 import BM25Okapi

BASE = os.path.dirname(os.path.abspath(__file__))
PDF = "Investigación Carrera TI Indoamérica Quito.pdf"
RERANKERS = ["cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"]
FRAGMENTACIONES = [(1500, 300), (1000, 200), (800, 160), (700, 140), (600, 120)]


def normalizar(t):
    return " ".join(t.split()).lower()


def rango(orden, chunks, gold):
    gold = [normalizar(g) for g in gold]
    return next((i + 1 for i, j in enumerate(orden[:5]) if any(g in normalizar(chunks[j]) for g in gold)), None)


def rrf(*listas, k=60):
    puntos = {}
    for lista in listas:
        for pos, idx in enumerate(lista):
            puntos[idx] = puntos.get(idx, 0) + 1 / (k + pos + 1)
    return sorted(puntos, key=puntos.get, reverse=True)


def metricas(rangos):
    n = len(rangos)
    return {"hit@1": sum(r == 1 for r in rangos if r) / n, "hit@2": sum(1 for r in rangos if r and r <= 2) / n, "hit@3": sum(1 for r in rangos if r and r <= 3) / n,
            "hit@5": sum(1 for r in rangos if r) / n, "mrr@5": sum(1 / r for r in rangos if r) / n}


def main():
    banco = json.load(open(os.path.join(BASE, "banco_preguntas.json"), encoding="utf-8"))["dominio"]
    md = pymupdf4llm.to_markdown(PDF)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    rerankers = {nombre: CrossEncoder(nombre, max_length=512) for nombre in RERANKERS}
    filas = []
    for size, overlap in FRAGMENTACIONES:
        chunks = MarkdownTextSplitter(chunk_size=size, chunk_overlap=overlap).split_text(md)
        matriz = embedder.encode(chunks, normalize_embeddings=True)
        bm25 = BM25Okapi([tokenizar_bm25(c) for c in chunks])
        resultados = {}
        for item in banco:
            consulta = preparar_consulta(item["pregunta"])
            densa = list(np.argsort(-(matriz @ embedder.encode(consulta, normalize_embeddings=True))))
            lexica = list(np.argsort(-bm25.get_scores(tokenizar_bm25(consulta))))
            hibrida = rrf(densa[:20], lexica[:20])
            ordenes = {"densa": densa, "bm25": lexica, "hibrida": hibrida}
            candidatos = hibrida[:20]
            for nombre, modelo in rerankers.items():
                puntajes = modelo.predict([(item["pregunta"], chunks[j]) for j in candidatos])
                ordenes[f"hibrida+{nombre.split('/')[-1]}"] = [candidatos[i] for i in np.argsort(-puntajes)]
            for estrategia, orden in ordenes.items():
                resultados.setdefault(estrategia, []).append(rango(orden, chunks, item["gold"]))
        for estrategia, rangos in resultados.items():
            fila = {"chunk_size": size, "chunk_overlap": overlap, "fragmentos": len(chunks), "estrategia": estrategia,
                    **{k: round(v, 4) for k, v in metricas(rangos).items()}}
            filas.append(fila)
            print(fila)
    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    with open(os.path.join(BASE, "resultados", "experimento_recuperacion.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)


if __name__ == "__main__":
    main()
