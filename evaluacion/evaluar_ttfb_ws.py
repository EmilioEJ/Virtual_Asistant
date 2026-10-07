"""
Medición de extremo a extremo del TTFB por WebSocket (/ws/chat) contra el servidor en ejecución.

Reproduce lo que hace el navegador: abre /ws/chat con la cookie de sesión, envía
{"message": ...} y mide el tiempo desde el envío hasta el primer fragmento de texto
({"type": "token"}) y hasta el final de la respuesta ({"type": "fin"}).

Se usa el banco de PRUEBA reservado. Las consultas se envían en la misma sesión,
por lo que el historial conversacional (últimos turnos) se incluye en el prompt,
igual que en una conversación real.

Uso (con el servidor levantado):
    .venv/bin/python evaluacion/evaluar_ttfb_ws.py <session_token> [url_base]
"""
import asyncio
import csv
import json
import os
import statistics
import sys
import time

import websockets

BASE = os.path.dirname(os.path.abspath(__file__))
CALENTAMIENTO = 2


def resumen(valores):
    v = sorted(valores)
    return {"n": len(v), "media": round(statistics.mean(v), 1), "desv_est": round(statistics.stdev(v), 1),
            "mediana": round(statistics.median(v), 1), "min": round(v[0], 1), "max": round(v[-1], 1),
            "p95": round(v[int(round(0.95 * (len(v) - 1)))], 1),
            "ic95_media": round(1.96 * statistics.stdev(v) / len(v) ** 0.5, 1)}


async def consultar(ws, pregunta):
    t0 = time.perf_counter()
    await ws.send(json.dumps({"message": pregunta}))
    ttfb = None
    while True:
        datos = json.loads(await ws.recv())
        if datos["type"] == "token" and ttfb is None:
            ttfb = (time.perf_counter() - t0) * 1000
        elif datos["type"] == "fin":
            return ttfb, (time.perf_counter() - t0) * 1000, datos
        elif datos["type"] == "error":
            raise RuntimeError(datos["detail"])


async def main():
    token = sys.argv[1]
    url = (sys.argv[2] if len(sys.argv) > 2 else "ws://127.0.0.1:8000").rstrip("/") + "/ws/chat"
    banco = json.load(open(os.path.join(BASE, "banco_prueba.json"), encoding="utf-8"))["dominio"]

    filas = []
    async with websockets.connect(url, additional_headers={"Cookie": f"session_token={token}"}) as ws:
        for _ in range(CALENTAMIENTO):  # carga del modelo y cachés (no se registra)
            await consultar(ws, "Hola")
        for item in banco:
            ttfb, total, fin = await consultar(ws, item["pregunta"])
            t = fin.get("timings", {})
            filas.append({"id": item["id"], "pregunta": item["pregunta"], "ttfb_ws_ms": round(ttfb, 1),
                          "ttfb_servidor_ms": t.get("ttfb_ms"), "rag_ms": t.get("rag_ms"),
                          "respuesta_completa_ms": round(total, 1), "respuesta": fin["reply"]})
            print(f"{item['id']}: ttfb={ttfb:.0f} ms total={total:.0f} ms -> {fin['reply'][:80]!r}")

    res = {
        "fecha": time.strftime("%Y-%m-%d %H:%M"),
        "endpoint": url,
        "n_preguntas": len(filas),
        "ttfb_ws_ms": resumen([f["ttfb_ws_ms"] for f in filas]),
        "ttfb_servidor_ms": resumen([f["ttfb_servidor_ms"] for f in filas]),
        "rag_ms": resumen([f["rag_ms"] for f in filas]),
        "respuesta_completa_ms": resumen([f["respuesta_completa_ms"] for f in filas]),
    }
    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    with open(os.path.join(BASE, "resultados", "ttfb_ws_detalle.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    with open(os.path.join(BASE, "resultados", "ttfb_ws_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
