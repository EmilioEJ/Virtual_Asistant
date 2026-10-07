# Evaluación reproducible del prototipo ARIA

Scripts usados en el Capítulo III del trabajo de titulación. Todos usan el mismo
código de producción (`api.py`, `rag_manager.py`) y guardan sus salidas en `resultados/`.

| Script | Qué mide | Servicios externos |
|---|---|---|
| `evaluar_rag.py` | Hit@1, Hit@3, Hit@5 y MRR@5 del recuperador de producción (híbrido + reordenador) en el banco de desarrollo y en el banco de prueba reservado | No |
| `experimento_recuperacion.py` | Comparación de estrategias (densa, BM25, híbrida, híbrida + reordenador) y tamaños de fragmento, solo con el banco de desarrollo | No |
| `experimento_chunking.py` | Sensibilidad de la recuperación densa al tamaño de fragmento | No |
| `evaluar_ttfb_ws.py <token> [url]` | TTFB de extremo a extremo por WebSocket (`/ws/chat`) contra el servidor en ejecución, banco de prueba | No (LLM local) |
| `generar_respuestas.py` | Respuestas para la clasificación manual de exactitud y verificación del rechazo fuera de dominio | No (LLM local) |
| `evaluar_latencia.py [N]` | Latencia STT, RAG, LLM y TTS, latencia percibida, WER y rechazo fuera de dominio | Groq, ElevenLabs, edge-tts |
| `evaluar_vision.py` | Inferencia de MediaPipe BlazeFace por fotograma y tamaño del mensaje de cajas delimitadoras (requiere un entorno aparte con `mediapipe`) | No |
| `prueba_presencia.py` | Eventos de llegada, salida y retorno del WebSocket `/ws` (rebote por fotogramas) y rechazo sin sesión | No |
| `prueba_seguridad.py` | Respuestas 401/403 de los endpoints, cierre 4401 de los WebSocket sin sesión y migración de hashes | No |

Ejecutar desde la raíz del proyecto, por ejemplo:

```bash
.venv/bin/python evaluacion/evaluar_rag.py
.venv/bin/python evaluacion/evaluar_latencia.py 30
.venv/bin/python evaluacion/evaluar_ttfb_ws.py <session_token>   # con el servidor levantado
```

`resultados/respuestas_ollama.csv` contiene la clasificación manual (correcta, parcial,
incorrecta, no responde) de las respuestas de Nemotron, contrastadas con el documento fuente.
`resultados/exactitud_respuestas.csv` conserva la clasificación de la versión anterior
(Llama 3.2 11B por la API de NVIDIA) para la comparación.

Configuración de Ollama usada en las mediciones: `LLAMA_ARG_CACHE_RAM=0` y
`LLAMA_ARG_CTX_CHECKPOINTS=0` (sin caché de prompts en RAM). Con los valores por defecto,
el proceso `llama-server` de Nemotron acumula hasta 8 GB de caché en RAM y el sistema
termina el servicio por falta de memoria.

La imagen `datos/astronaut.png` (NASA, dominio público) proviene de scikit-image y se usa
como fotograma de prueba con rostro.
