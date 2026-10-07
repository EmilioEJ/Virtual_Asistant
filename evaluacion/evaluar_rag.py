"""
Evaluación reproducible del motor de recuperación (RAG).

Usa el mismo Recuperador de producción que api.py: búsqueda densa (MiniLM +
ChromaDB) y léxica (BM25) fusionadas por RRF y reordenadas con un cross-encoder.
Un fragmento es relevante si contiene alguna de las frases gold de la pregunta.

Se reportan por separado el banco de DESARROLLO (banco_preguntas.json, usado para
elegir la configuración) y el banco de PRUEBA reservado (banco_prueba.json, no
usado para ajustar parámetros). La cifra final del sistema es la del banco de prueba.

Métricas: Hit@1, Hit@3 (Top-K usado en producción), Hit@5 y MRR@5.

Uso (desde la raíz del proyecto):
    .venv/bin/python evaluacion/evaluar_rag.py
"""
import csv
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from sentence_transformers import SentenceTransformer

from rag_manager import COLLECTION_NAME, EMBEDDING_MODEL, RAG_TOP_K, Recuperador, cargar_reranker, preparar_consulta

BASE = os.path.dirname(os.path.abspath(__file__))
K_MAX = 5
BANCOS = {"desarrollo": "banco_preguntas.json", "prueba": "banco_prueba.json"}


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip().lower()


def es_relevante(fragmento: str, gold: list[str]) -> bool:
    frag = normalizar(fragmento)
    return any(normalizar(g) in frag for g in gold)


def evaluar_banco(nombre, preguntas, recuperador, todos):
    # Validación del gold standard: cada frase debe existir en el corpus indexado
    for item in preguntas:
        if not any(es_relevante(d, item["gold"]) for d in todos):
            raise SystemExit(f"Gold standard de {nombre}/{item['id']} no aparece en ningún fragmento: {item['gold']}")

    filas = []
    for item in preguntas:
        t0 = time.perf_counter()
        docs = recuperador.buscar(item["pregunta"], K_MAX)
        ms = (time.perf_counter() - t0) * 1000
        rango = next((i + 1 for i, d in enumerate(docs) if es_relevante(d, item["gold"])), None)
        filas.append({
            "banco": nombre,
            "id": item["id"],
            "categoria": item["categoria"],
            "pregunta": item["pregunta"],
            "rango_primer_relevante": rango or "",
            "hit@1": int(rango is not None and rango <= 1),
            f"hit@{RAG_TOP_K}": int(rango is not None and rango <= RAG_TOP_K),
            "hit@5": int(rango is not None),
            "rr@5": round(1 / rango, 4) if rango else 0.0,
            "latencia_recuperacion_ms": round(ms, 1),
        })

    n = len(filas)
    lat = sorted(f["latencia_recuperacion_ms"] for f in filas[1:])  # se descarta la 1.ª (calentamiento)
    resumen = {
        "n_preguntas": n,
        "hit@1": round(sum(f["hit@1"] for f in filas) / n, 4),
        f"hit@{RAG_TOP_K}": round(sum(f[f"hit@{RAG_TOP_K}"] for f in filas) / n, 4),
        "hit@5": round(sum(f["hit@5"] for f in filas) / n, 4),
        "mrr@5": round(sum(f["rr@5"] for f in filas) / n, 4),
        "latencia_recuperacion_ms_media": round(sum(lat) / len(lat), 1),
        "latencia_recuperacion_ms_p95": lat[int(0.95 * (len(lat) - 1))],
        "fallos": [f["id"] for f in filas if not f[f"hit@{RAG_TOP_K}"]],
    }
    return filas, resumen


def main():
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    coleccion = chromadb.PersistentClient(path="./chroma_db").get_collection(COLLECTION_NAME)
    recuperador = Recuperador(embedder, coleccion, cargar_reranker())
    todos = recuperador.docs

    resumen = {"fragmentos_indexados": coleccion.count(), "top_k_produccion": RAG_TOP_K}
    filas = []
    for nombre, archivo in BANCOS.items():
        banco = json.load(open(os.path.join(BASE, archivo), encoding="utf-8"))
        recuperador.buscar("calentamiento")
        filas_banco, resumen[nombre] = evaluar_banco(nombre, banco["dominio"], recuperador, todos)
        filas += filas_banco

    # Similitud coseno del Top-1 denso en preguntas fuera de dominio (referencia para umbrales)
    banco = json.load(open(os.path.join(BASE, BANCOS["desarrollo"]), encoding="utf-8"))
    sims = {}
    for grupo in ("dominio", "fuera_de_dominio"):
        valores = []
        for item in banco[grupo]:
            emb = embedder.encode(preparar_consulta(item["pregunta"])).tolist()
            res = coleccion.query(query_embeddings=[emb], n_results=1, include=["distances"])
            valores.append(1 - res["distances"][0][0])
        sims[grupo] = round(sum(valores) / len(valores), 4)
    resumen["similitud_top1_dominio_media"] = sims["dominio"]
    resumen["similitud_top1_fuera_dominio_media"] = sims["fuera_de_dominio"]

    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    with open(os.path.join(BASE, "resultados", "rag_detalle.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    with open(os.path.join(BASE, "resultados", "rag_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
