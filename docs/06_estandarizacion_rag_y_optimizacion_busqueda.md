# 06 - Estandarización de Modelos y Optimización de Búsqueda Semántica (RAG)

## Contexto y Problema Detectado
El Asistente Virtual presentaba inconsistencias críticas al responder preguntas estructuradas sobre la malla curricular (por ejemplo, "qué asignaturas hay en el primer nivel"). Tras una auditoría exhaustiva del pipeline RAG (Retrieval-Augmented Generation), se identificaron tres problemas fundamentales que rompían el motor de inferencia:

1. **Desfase del Modelo de Embeddings:** El script de administración (`rag_manager.py`) encargado de ingestar y procesar los PDFs usaba el modelo `all-MiniLM-L6-v2` (optimizado para inglés). Sin embargo, el script de chat (`api.py`) intentaba recuperar la información usando `paraphrase-multilingual-MiniLM-L12-v2`. Esto causaba una incompatibilidad total en el espacio vectorial matemático (similitud del coseno), resultando en la recuperación de fragmentos basura o aleatorios.
2. **Inconsistencia en el Chunking:** Los tamaños de fraccionamiento variaban dependiendo de si la base se construía mediante consola o mediante el panel de administración (1500 vs 2500 caracteres), lo que causaba resultados impredecibles.
3. **Limitación de Contexto de Recuperación:** El sistema recuperaba únicamente 6 fragmentos, lo cual era insuficiente para preguntas complejas o semánticamente dispersas como descripciones enteras de niveles académicos.

## Solución Implementada

### 1. Unificación Absoluta del Modelo Matemático
Se reescribió la lógica en `rag_manager.py` para obligar al panel de administración a usar el mismo modelo de embeddings que utiliza el motor de búsqueda en español.
- **Modelo Estandarizado:** `paraphrase-multilingual-MiniLM-L12-v2` (utilizado en todo el backend).

### 2. Normalización de Chunking
Se redujo el tamaño de los fragmentos a un umbral más lógico y unificado para todo el sistema (tanto `build_rag_index.py` como `rag_manager.py`):
- **chunk_size:** 1500 caracteres.
- **chunk_overlap:** 300 caracteres.
Este tamaño es el ideal para albergar tablas de la malla curricular sin inyectar ruido excesivo.

### 3. Normalización Semántica y Expansión de Búsqueda (`api.py`)
- Se implementó un diccionario de normalización semántica en la entrada del usuario usando expresiones regulares (Regex). Términos como "1er", "semestre" y "materia" ahora se traducen internamente a "primer", "nivel" y "asignatura" para maximizar la similitud con el léxico estricto del documento oficial.
- Se amplió el radar de búsqueda (K-Retrieval) de `n_results=6` a **`n_results=16`**. Dado que el LLM (Groq / Llama 3) posee una ventana de contexto de 8K tokens, recuperar 16 fragmentos (aprox. 5,000 tokens) provee al bot de contexto hiperdetallado sin desbordar el modelo.

## Conclusión
La base de datos `chroma_db` fue reconstruida exitosamente aplicando estos nuevos estándares. Cualquier documento que se actualice a futuro a través del panel de Administración RAG respetará el chunking (1500) y el embedder multilingüe, garantizando respuestas deterministas y de alta precisión.
