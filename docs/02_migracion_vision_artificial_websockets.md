# ADR 02: Migración de Visión Artificial a WebSockets

## Fecha
14 de Julio de 2026

## Contexto
El Asistente Virtual original estaba diseñado para ejecutarse localmente, utilizando la cámara web conectada al ordenador mediante la librería OpenCV en Python (`cv2.VideoCapture(0)`). Esta arquitectura funcionaba a la perfección en desarrollo, ya que el script de Python tenía acceso directo al hardware del usuario.

El problema surgió al desplegar la aplicación en un servidor en la nube (DigitalOcean). Los servidores virtuales carecen de periféricos físicos como cámaras web. Al intentar ejecutar la tarea en segundo plano que iniciaba la cámara, el sistema fallaba porque `VideoCapture` no encontraba ningún dispositivo `/dev/video0`.

## Decisión
Se decidió rediseñar por completo la arquitectura de captura y procesamiento visual:
1. **Delegación de hardware al Cliente (Frontend):** En lugar de que Python intente acceder a una cámara, es el navegador del usuario (Chrome/Firefox) quien solicita permiso para usar la cámara web mediante JavaScript (`navigator.mediaDevices.getUserMedia`).
2. **Streaming por WebSockets:** Se implementó una conexión bidireccional en tiempo real (`/ws`) entre el navegador y FastAPI.
3. **Procesamiento de Fotogramas (Backend):** El frontend extrae fotogramas del video en formato `base64` y los envía periódicamente al servidor. El servidor decodifica estos strings a matrices NumPy y realiza la detección de rostros mediante los algoritmos de OpenCV en la nube.
4. **Respuesta Inmediata:** Si OpenCV detecta que una persona acaba de aparecer o desaparecer, envía una notificación por el WebSocket al frontend para que el Avatar 3D salude o se despida de forma proactiva.

## Consecuencias
**Positivas:**
- El sistema ahora es agnóstico del hardware del servidor: se puede desplegar en cualquier contenedor o nube sin requerir hardware de cámara.
- La aplicación web interactúa verdaderamente con la persona que está frente a la pantalla en cualquier parte del mundo, no con quien está sentado frente al servidor físico.

**Negativas / A considerar:**
- Mayor latencia de red: Enviar fotogramas en formato `base64` de forma continua consume ancho de banda.
- Necesidad obligatoria de **HTTPS**: Los navegadores modernos por seguridad bloquean el acceso a la cámara y al micrófono (getUserMedia) a menos que la web se sirva mediante `https://` o se ejecute en `localhost`. Esto obligó a la generación de certificados SSL para el entorno de producción.
