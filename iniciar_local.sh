#!/bin/bash
echo "🚀 Iniciando el Asistente Virtual en Modo Local..."
echo "Podrás acceder en: http://localhost:8000"
echo "=================================================="
echo "⚠️  NOTA: En localhost (modo local), los navegadores sí permiten acceso"
echo "   a la cámara y micrófono sin necesidad de HTTPS (SSL)."
echo "=================================================="
echo "Presiona Ctrl+C para detener."

# Ejecutar con recarga automática para desarrollo
.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000 --reload
