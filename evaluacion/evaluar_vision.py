"""
Benchmark del módulo de visión (detección de presencia en el cliente).

El navegador ejecuta MediaPipe Face Detector con el modelo BlazeFace de corto alcance
(static/models/blaze_face_short_range.tflite) y envía al WebSocket /ws solo las cajas
delimitadoras: {"cajas": [[x, y, ancho, alto], ...]}. Este script ejecuta el mismo
modelo con la API de Python de MediaPipe (mismo motor TFLite en CPU) para medir:
  - el tiempo de inferencia por fotograma a 320x240 y 640x480,
  - el número de rostros detectados con y sin rostro (sin falsas detecciones),
  - el tamaño del mensaje WebSocket con cajas frente al envío anterior de JPEG en base64.

En el navegador la inferencia corre en WebAssembly/WebGL, por lo que el tiempo real
depende del equipo del usuario; esta medición es una referencia del costo del modelo.

Imagen de prueba: "astronaut" (NASA, dominio público), incluida en scikit-image.

Requiere mediapipe, que fija protobuf<5 y entra en conflicto con chromadb; se ejecuta
en un entorno aparte:
    python3 -m venv /tmp/venv_mp && /tmp/venv_mp/bin/pip install mediapipe==0.10.14 opencv-python-headless
    /tmp/venv_mp/bin/python evaluacion/evaluar_vision.py
"""
import base64
import json
import os
import platform
import statistics
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, RunningMode

BASE = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(os.path.dirname(BASE), "static", "models", "blaze_face_short_range.tflite")
REPETICIONES = 300


def a_resolucion(imagen, ancho, alto):
    """Recorte a 4:3 (como una webcam) y redimensionado."""
    h, w = imagen.shape[:2]
    if w * 3 != h * 4:
        nuevo_h = w * 3 // 4
        imagen = imagen[:nuevo_h] if nuevo_h <= h else imagen
    return cv2.resize(imagen, (ancho, alto))


def mensaje_cajas(detecciones):
    """Réplica del mensaje que envía script.js al WebSocket /ws."""
    cajas = [[c.origin_x, c.origin_y, c.width, c.height] for c in (d.bounding_box for d in detecciones)]
    return json.dumps({"cajas": cajas})


def mensaje_jpeg(frame):
    """Mensaje que enviaba la versión anterior: canvas.toDataURL('image/jpeg', 0.5)."""
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


def main():
    opciones = FaceDetectorOptions(base_options=BaseOptions(model_asset_path=MODELO),
                                   running_mode=RunningMode.IMAGE, min_detection_confidence=0.5)
    detector = FaceDetector.create_from_options(opciones)

    con_rostro = cv2.imread(os.path.join(BASE, "datos", "astronaut.png"))
    rng = np.random.default_rng(0)
    sin_rostro = np.clip(200 + rng.normal(0, 20, (480, 640, 3)), 0, 255).astype(np.uint8)

    resultados = {"cpu": platform.processor() or platform.machine(), "mediapipe": mp.__version__,
                  "modelo": os.path.basename(MODELO), "repeticiones": REPETICIONES, "casos": []}
    for nombre, imagen in [("con_rostro", con_rostro), ("sin_rostro", sin_rostro)]:
        for ancho, alto in [(320, 240), (640, 480)]:
            frame = a_resolucion(imagen, ancho, alto)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            detector.detect(mp_img)  # calentamiento
            tiempos = []
            for _ in range(REPETICIONES):
                t0 = time.perf_counter()
                detecciones = detector.detect(mp_img).detections
                tiempos.append((time.perf_counter() - t0) * 1000)
            caso = {"imagen": nombre, "resolucion": f"{ancho}x{alto}",
                    "ms_media": round(statistics.mean(tiempos), 2),
                    "ms_desv_est": round(statistics.stdev(tiempos), 2),
                    "ms_p95": round(sorted(tiempos)[int(0.95 * (len(tiempos) - 1))], 2),
                    "rostros_detectados": len(detecciones),
                    "bytes_mensaje_cajas": len(mensaje_cajas(detecciones)),
                    "bytes_mensaje_jpeg_anterior": len(mensaje_jpeg(frame)),
                    # Fracción de un núcleo ocupada a 1 fotograma/s (frecuencia del frontend)
                    "uso_cpu_1fps_pct": round(statistics.mean(tiempos) / 1000 * 100, 2)}
            resultados["casos"].append(caso)
            print(caso)

    os.makedirs(os.path.join(BASE, "resultados"), exist_ok=True)
    with open(os.path.join(BASE, "resultados", "vision_resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
