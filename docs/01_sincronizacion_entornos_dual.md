# ADR 01: Arquitectura de Entornos Duales (Local y Servidor)

## Fecha
14 de Julio de 2026

## Contexto
El desarrollo inicial del Asistente Virtual se realizó íntegramente en un entorno local (localhost). A medida que el proyecto creció, surgió la necesidad de desplegar el sistema en un servidor remoto de DigitalOcean (`63.141.255.7`) para su acceso público.
Inicialmente se consideró crear y mantener dos repositorios o carpetas separadas (una para la versión local y otra para la de producción). Sin embargo, esto presentaba un alto riesgo de inconsistencias de código, duplicación de esfuerzo y problemas al mantener las ramas sincronizadas (por ejemplo, tener que cambiar configuraciones de red, IPs o certificados SSL manualmente entre entornos).

## Decisión
Se decidió mantener una **única carpeta raíz (single source of truth)** para el código fuente del proyecto (`/home/emilioej/EmilioEJ/Asistente_Virtual/`). 
Para manejar los entornos, se optó por la automatización mediante scripts de Shell:

1. **`iniciar_local.sh`**: Inicia el entorno virtual y ejecuta el servidor FastAPI en `localhost` usando configuraciones amigables para desarrollo local.
2. **`desplegar_servidor.sh`**: Ejecuta un comando `rsync` optimizado para empaquetar y transferir únicamente los cambios de código fuente hacia el servidor remoto, excluyendo bases de datos temporales, cachés y certificados locales mediante un `.gitignore` y filtros de rsync.

## Consecuencias
**Positivas:**
- Mayor velocidad de desarrollo: se prueba en local y con un solo comando (`./desplegar_servidor.sh`) el cambio ya está en la nube.
- Reducción del "code drift" (diferencias de código entre el entorno de desarrollo y producción).
- No hay duplicación innecesaria de archivos pesados.

**Negativas / A considerar:**
- Si un desarrollador edita código directamente en el servidor remoto por error, ese código se sobreescribirá y perderá la próxima vez que se ejecute el script `desplegar_servidor.sh`. (Todo desarrollo DEBE hacerse en local).
