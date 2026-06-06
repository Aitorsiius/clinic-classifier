# Backend Service — Clasificador CIE-10

Núcleo de búsqueda semántica de códigos CIE-10-ES. Combina una base de datos vectorial (Qdrant)
con un modelo *bi-encoder* de *embeddings* y un *cross-encoder* de *reranking* para devolver los
códigos más relevantes ante una consulta clínica en lenguaje natural.

> El código de la aplicación reside en `cie_classifier/` (API en `api.py`, lógica en `main.py`).

## Propósito

- Recuperar candidatos CIE-10 desde Qdrant a partir de los *embeddings* de la consulta.
- Reordenar (re-rank) los candidatos con un *cross-encoder* para mejorar la precisión.
- Exponer la búsqueda al resto del sistema y registrar la actividad en el `log-service`.
- Permitir la exportación de resultados a CSV.

## Puerto

- **8000** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Información del servicio |
| GET | `/health` | Estado del servicio |
| POST | `/search` | Búsqueda semántica de códigos CIE-10 |
| POST | `/export-csv` | Exportación de resultados a CSV |

## Servicios de inferencia asociados

- **embeddings** (puerto 8002): bi-encoder `intfloat/multilingual-e5-base` (HuggingFace TEI).
- **reranker** (puerto 8001): cross-encoder `cross-encoder/ms-marco-MiniLM-L-12-v2` (HuggingFace TEI).

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `EMBEDDING_URL` | Endpoint del servicio de *embeddings* |
| `RERANKER_URL` | Endpoint del servicio de *reranking* |
| `LLM_QUERY_PROCESSOR_URL` | URL del procesador de consultas LLM |
| `LOG_SERVICE_URL` | URL del servicio de logs |
| `BACKEND_PORT` | Puerto de escucha (por defecto `8000`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · qdrant-client · requests · httpx
