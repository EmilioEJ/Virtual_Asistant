"""
Pruebas de control de acceso (RNF-08) sobre una copia temporal de users.db.

Verifica que los endpoints protegidos rechazan peticiones sin sesión (401 en HTTP,
cierre 4401 en los WebSocket /ws/chat y /ws),
que un usuario regular no accede a rutas de administración (403) y que los
hashes SHA-256 legados se migran a PBKDF2 al iniciar sesión.

En la copia temporal se asigna al usuario regular una contraseña de prueba aleatoria
con el esquema anterior (SHA-256 sin salt), por lo que no se necesita la clave real
ni se modifica la base de usuarios del prototipo.

Uso (desde la raíz del proyecto):
    .venv/bin/python evaluacion/prueba_seguridad.py
"""
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
USUARIO = "eespinozajimenez"


def main():
    clave = secrets.token_urlsafe(16)
    trabajo = tempfile.mkdtemp()
    for nombre in ("users.db", "chroma_db", "static"):
        origen = os.path.join(RAIZ, nombre)
        (shutil.copytree if os.path.isdir(origen) else shutil.copy)(origen, os.path.join(trabajo, nombre))
    os.chdir(trabajo)
    os.environ["AI_PROVIDER"] = "none"
    conn = sqlite3.connect("users.db")
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                 (hashlib.sha256(clave.encode()).hexdigest(), USUARIO))
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import api

    casos = []
    with TestClient(api.app) as c:
        for metodo, ruta, esperado in [("post", "/api/chat", 401), ("post", "/api/tts", 401),
                                       ("post", "/api/stt", 401), ("get", "/debug/rag?q=x", 401),
                                       ("get", "/debug/md", 401), ("get", "/api/admin/rag_status", 401)]:
            kwargs = {"json": {"message": "hola"}} if ruta in ("/api/chat", "/api/tts") else {}
            casos.append(("sin sesión", ruta, esperado, getattr(c, metodo)(ruta, **kwargs).status_code))
        # Los WebSocket de chat y presencia se cierran con el código 4401 si no hay sesión
        for ruta in ("/ws/chat", "/ws"):
            try:
                with c.websocket_connect(ruta) as ws:
                    ws.receive_text()
                codigo = None
            except WebSocketDisconnect as e:
                codigo = e.code
            casos.append(("sin sesión", ruta, 4401, codigo))
        casos.append(("clave errónea", "/api/login", 401,
                      c.post("/api/login", json={"username": USUARIO, "password": "x"}).status_code))
        casos.append(("usuario regular", "/api/login", 200,
                      c.post("/api/login", json={"username": USUARIO, "password": clave}).status_code))
        for ruta in ("/debug/rag?q=x", "/api/admin/rag_status"):
            casos.append(("usuario regular", ruta, 403, c.get(ruta).status_code))
    hash_final = sqlite3.connect("users.db").execute(
        "SELECT password_hash FROM users WHERE username = ?", (USUARIO,)).fetchone()[0]

    resultado = {"casos": [dict(zip(("escenario", "ruta", "esperado", "obtenido"), x)) for x in casos],
                 "aprobados": sum(x[2] == x[3] for x in casos), "total": len(casos),
                 "hash_pbkdf2_tras_login": hash_final.startswith("pbkdf2_sha256$")}
    os.makedirs(os.path.join(RAIZ, "evaluacion", "resultados"), exist_ok=True)
    with open(os.path.join(RAIZ, "evaluacion", "resultados", "seguridad_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == "__main__":
    main()
