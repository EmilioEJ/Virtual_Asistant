# ADR 04: Optimización del RAG y Modelo Multilingüe

## Fecha
14 de Julio de 2026

## Contexto
El Asistente Virtual fallaba sistemáticamente al intentar responder preguntas muy básicas extraídas directamente del documento PDF (ej: duración de la carrera, semestres, modalidades). Al realizar una auditoría del sistema de Recuperación de Información (RAG), se identificó que el motor estaba utilizando el modelo de embeddings `all-MiniLM-L6-v2`. Este modelo está altamente optimizado pero entrenado primordialmente para el idioma inglés. Al procesar preguntas en español, los vectores generados no lograban coincidir semánticamente con los fragmentos del documento, provocando que la base de datos devolviera resultados vacíos o irrelevantes.

## Decisión
Se decidió intervenir profundamente en el motor de embeddings y el proceso de fraccionamiento de texto (chunking):
1. **Cambio de Modelo de Embeddings**: Se reemplazó `all-MiniLM-L6-v2` por `paraphrase-multilingual-MiniLM-L12-v2` tanto en el indexador (`build_rag_index.py`) como en el servidor FastAPI (`api.py`). Este modelo está diseñado para mapear el significado semántico a través de más de 50 idiomas, logrando que las consultas en español coincidan de manera precisa con el texto.
2. **Ajuste del Chunking**: Se redujo el tamaño de los fragmentos generados por `MarkdownTextSplitter` de 2500 a 1500 caracteres, con un solapamiento de 300. Fragmentos más cortos permiten que la búsqueda vectorial encuentre párrafos muy específicos sin diluir la "atención" del vector en demasiado texto.
3. **Reconstrucción Vectorial**: Se eliminó la caché antigua (`chroma_db/`) y se re-ejecutó el indexador para generar los nuevos vectores multilingües de 384 dimensiones.

## Consecuencias
**Positivas:**
- Precisión drásticamente mejorada. El sistema ahora entiende sinónimos, jerga y preguntas formuladas de distintas formas en español.
- Las consultas de prueba ("cuantos niveles o semestres tiene la malla curricular") ahora devuelven exactamente los fragmentos que contienen las mallas académicas.

**Negativas / A considerar:**
- El modelo `paraphrase-multilingual-MiniLM-L12-v2` es ligeramente más pesado que su contraparte en inglés, lo que incrementó el tiempo inicial de descarga e inicialización del servidor la primera vez, aunque la latencia por cada pregunta se mantiene en milisegundos.
