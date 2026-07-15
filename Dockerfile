# Imagen del backend de Aria (FastAPI + RAG). Sirve HTTP plano en :8000;
# Traefik (en el VPS) termina el TLS. Se fuerza CPU (el modelo LLM vive en el GPU
# remoto, accedido por el sidecar 'ollama-tunnel').
FROM python:3.11-slim

# Dependencias de sistema para OpenCV (visión) y compilación de wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sin GPU: usar torch CPU (evita descargar el build CUDA gigante).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-descargar el embedder multilingüe para no pagar la latencia en el primer request.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

COPY . .

# El modelo corre en el GPU remoto; el contenedor no usa CUDA local.
ENV CUDA_VISIBLE_DEVICES=""

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
