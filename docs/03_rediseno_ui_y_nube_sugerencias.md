# ADR 03: Rediseño UI (Modo Conversacional y Sugerencias)

## Fecha
14 de Julio de 2026

## Contexto
Durante las pruebas de usabilidad del Asistente Virtual, se observaron tres oportunidades de mejora en la interfaz:
1. Al cargar la página, el usuario entraba directamente a un modo de chat textual tradicional, perdiendo el impacto innovador de un avatar de voz interactivo de primera impresión.
2. Los nuevos usuarios a menudo no sabían qué preguntas hacerle al asistente respecto a la carrera de Ingeniería en TI.
3. El avatar tenía un código habilitado para seguir constantemente el cursor del ratón con sus ojos y cuello, lo cual a veces generaba posturas incómodas o distraía al usuario durante las respuestas habladas.

## Decisión
Se implementaron tres soluciones visuales y lógicas de gran impacto para mejorar el "Onboarding" del usuario:

1. **Modo Conversacional por Defecto**:
   - En `index.html` y `script.js` se invirtió el modo predeterminado. Al iniciar sesión, la UI ahora muestra el panel del Micrófono grande, fomentando de inmediato la interacción oral.
2. **Nube Interactiva de Sugerencias**:
   - Se analizaron los datos de la Universidad (malla curricular, modalidades, título, empleabilidad y ubicación) y se crearon "Burbujas flotantes" con estas sugerencias.
   - Para no saturar la vista principal, estas burbujas se colocaron flotando con posición absoluta (`position: absolute;`) dentro del panel del Avatar 3D (`.avatar-panel`). 
   - Se configuró la UI (arreglando bugs con el selector CSS global `button {}`) para que las burbujas adopten una forma alargada de píldora y tengan animaciones de flotabilidad (`@keyframes floating`). Al pulsar sobre ellas, el Asistente lee en voz alta automáticamente la respuesta.
3. **Desactivación del Seguimiento de Ratón (Mouse Tracking)**:
   - Se removió el código que ataba las variables de rotación `targetHeadX`, `targetHeadY`, `targetEyeX` y `targetEyeY` al cursor del mouse. 
   - Se asignaron valores neutros con pequeños osciladores senoidales (`Math.sin()`) para que el avatar mire permanentemente al frente de forma natural.

## Consecuencias
**Positivas:**
- Mayor atractivo visual inmediato y reducción de fricción: los usuarios no se sienten perdidos al tener opciones interactivas flotando a la vista.
- El Avatar luce más "enfocado" y profesional al estar siempre mirando al frente en vez de persiguiendo frenéticamente el cursor en la pantalla.
