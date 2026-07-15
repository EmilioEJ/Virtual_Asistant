#!/bin/bash
SERVER="eespinozajimenez@63.141.255.7"
PORT="22"

echo "☁️ Iniciando despliegue al servidor remoto ($SERVER)..."
echo "1. Sincronizando archivos (subiendo cambios locales)..."

# Sincronizamos todo, omitiendo el entorno virtual, caché, la BD de usuarios y git
rsync -avz -e "ssh -p $PORT -o StrictHostKeyChecking=no" \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude 'chroma_db' \
    --exclude 'users.db' \
    --exclude 'cert.pem' \
    --exclude 'key.pem' \
    --exclude 'iniciar_local.sh' \
    --exclude 'desplegar_servidor.sh' \
    ./ $SERVER:~/Asistente_Virtual/

if [ $? -eq 0 ]; then
    echo "2. Sincronización exitosa. Reiniciando el servicio en el servidor..."
    ssh -p $PORT -o StrictHostKeyChecking=no $SERVER 'systemctl --user restart asistente.service'
    if [ $? -eq 0 ]; then
        echo "✅ Despliegue completado con éxito."
        echo "🌐 El servidor debería estar disponible en: https://63.141.255.7:18000/"
    else
        echo "❌ Error al reiniciar el servicio remoto. (Asegúrate de que el servidor esté encendido)"
    fi
else
    echo "❌ Error durante la sincronización. (Asegúrate de que el servidor esté encendido y conectado a internet)"
fi
