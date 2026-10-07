"""
Análisis de sensibilidad del tamaño de fragmento (chunking) sobre la recuperación.
No modifica el índice de producción: re-fragmenta el PDF en memoria con varias
configuraciones y mide Hit@1, Hit@3 y MRR@5 con el mismo banco de preguntas.

Uso: .venv/bin/python evaluacion/experimento_chunking.py
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pymupdf4llm
from langchain_text_splitters import MarkdownTextSplitter
from sentence_transformers import SentenceTransformer

from rag_manager import EMBEDDING_MODEL, preparar_consulta

BASE = os.path.dirname(os.path.abspath(__file__))
PDF = "Investigación Carrera TI Indoamérica Quito.pdf"
CONFIGURACIONES = [(1500, 300), (1000, 200), (800, 160), (600, 120)]


def normalizar(texto):
    return re.sub(r"\s+", " ", texto).strip().lower()


def main():
    banco = json.load(open(os.path.join(BASE, "banco_preguntas.json"), encoding="utf-8"))["dominio"]
    md = pymupdf4llm.to_markdown(PDF)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    filas = []
    for size, overlap in CONFIGURACIONES:
        chunks = MarkdownTextSplitter(chunk_size=size, chunk_overlap=overlap).split_text(md)
        matriz = embedder.encode(chunks, normalize_embeddings=True)
        h1 = h3 = rr = 0.0
        for item in banco:
            v = embedder.encode(preparar_consulta(item["pregunta"]), normalize_embeddings=True)
            orden = np.argsort(-(matriz @ v))[:5]
            gold = [normalizar(g) for g in item["gold"]]
            rango = next((i + 1 for i, j in enumerate(orden) if any(g in normalizar(chunks[j]) for g in gold)), None)
            h1 += rango == 1
            h3 += bool(rango and rango <= 3)
            rr += 1 / rango if rango else 0
        n = len(banco)
        filas.append({"chunk_size": size, "chunk_overlap": overlap, "fragmentos": len(chunks),
                      "hit@1": round(h1 / n, 4), "hit@3": round(h3 / n, 4), "mrr@5": round(rr / n, 4)})
        print(filas[-1])
    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    with open(os.path.join(BASE, "resultados", "experimento_chunking.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)


if __name__ == "__main__":
    main()
