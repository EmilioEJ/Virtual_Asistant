"""
Prueba de los eventos de presencia (RF-06).

1. Lógica de rebote: se alimenta api.DetectorPresencia con secuencias de detecciones
   (una por fotograma, como envía el navegador) y se verifica en qué fotograma se
   emiten person_arrived y person_left, incluido el retorno del usuario.
2. Integración: sobre una copia temporal de users.db, se abre el WebSocket /ws con una
   sesión de prueba, se envían cajas delimitadoras y se comprueba que llegan los eventos.

Uso (desde la raíz del proyecto):
    .venv/bin/python evaluacion/prueba_presencia.py
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
CAJA = [[100, 80, 90, 110]]

# (escenario, detecciones por fotograma, eventos esperados como (fotograma, evento))
ESCENARIOS = [
    ("Llegada, salida y retorno", [CAJA] * 3 + [[]] * 5 + [CAJA] * 2,
     [(2, "person_arrived"), (7, "person_left"), (10, "person_arrived")]),
    ("Rostro en un solo fotograma (ruido)", [CAJA] + [[]] * 3, []),
    ("Ausencia breve de 3 fotogramas", [CAJA] * 2 + [[]] * 3 + [CAJA] * 2, [(2, "person_arrived")]),
]


def main():
    trabajo = tempfile.mkdtemp()
    for nombre in ("users.db", "chroma_db", "static"):
        origen = os.path.join(RAIZ, nombre)
        (shutil.copytree if os.path.isdir(origen) else shutil.copy)(origen, os.path.join(trabajo, nombre))
    os.chdir(trabajo)
    os.environ["AI_PROVIDER"] = "none"

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import api

    casos = []
    for escenario, secuencia, esperados in ESCENARIOS:
        detector = api.DetectorPresencia()
        obtenidos = [(i, e) for i, cajas in enumerate(secuencia, start=1)
                     if (e := detector.actualizar(bool(cajas)))]
        casos.append({"escenario": escenario, "esperados": esperados, "obtenidos": obtenidos,
                      "aprobado": obtenidos == esperados})

    conn = sqlite3.connect("users.db")
    usuario = conn.execute("SELECT username FROM users LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO sessions (session_token, username) VALUES (?, ?)", ("prueba-presencia", usuario))
    conn.commit()
    conn.close()
    with TestClient(api.app) as c:
        try:
            with c.websocket_connect("/ws") as ws:
                ws.receive_text()
            sin_sesion = None
        except WebSocketDisconnect as e:
            sin_sesion = e.code
        c.cookies.set("session_token", "prueba-presencia")
        with c.websocket_connect("/ws") as ws:
            for cajas in [CAJA] * 2:
                ws.send_text(json.dumps({"cajas": cajas}))
            llegada = ws.receive_text()
            for cajas in [[]] * 4:
                ws.send_text(json.dumps({"cajas": cajas}))
            salida = ws.receive_text()
    casos.append({"escenario": "WebSocket /ws sin sesión", "esperados": 4401, "obtenidos": sin_sesion,
                  "aprobado": sin_sesion == 4401})
    casos.append({"escenario": "WebSocket /ws con sesión", "esperados": ["person_arrived", "person_left"],
                  "obtenidos": [llegada, salida], "aprobado": [llegada, salida] == ["person_arrived", "person_left"]})

    resultado = {"casos": casos, "aprobados": sum(c["aprobado"] for c in casos), "total": len(casos),
                 "fotogramas_llegada": api.FOTOGRAMAS_LLEGADA, "fotogramas_salida": api.FOTOGRAMAS_SALIDA}
    os.makedirs(os.path.join(RAIZ, "evaluacion", "resultados"), exist_ok=True)
    with open(os.path.join(RAIZ, "evaluacion", "resultados", "presencia_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == "__main__":
    main()
