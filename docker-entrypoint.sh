#!/bin/sh
# Arranque idempotente del backend de Aria.
set -e

# 1) Base de usuarios (login del panel). users.db está gitignored; se crea si falta.
if [ ! -f /app/users.db ]; then
    echo "🔐 Inicializando base de usuarios (users.db)..."
    python init_db.py
fi

# 2) Índice RAG. chroma_db/ se monta como volumen persistente; si está vacío, se construye
#    desde el PDF incluido en el repo.
if [ -z "$(ls -A /app/chroma_db 2>/dev/null)" ]; then
    echo "🧠 Construyendo índice RAG (ChromaDB) desde el PDF..."
    python build_rag_index.py || echo "⚠️  No se pudo construir el índice RAG; el chat funcionará sin contexto."
fi

# 3) Servir HTTP plano; Traefik termina el TLS en el VPS.
echo "🚀 Arrancando uvicorn en 0.0.0.0:8000..."
exec uvicorn api:app --host 0.0.0.0 --port 8000
