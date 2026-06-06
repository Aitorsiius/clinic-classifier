# LLM Query Processor Service

Servicio de procesado de consultas mediante un modelo de lenguaje (Vertex AI — Gemini). Analiza,
corrige y reformula las consultas clínicas para mejorar la calidad de la búsqueda de códigos CIE-10.

## Propósito

- **Analizar** la intención y entidades de la consulta del usuario.
- **Corregir** errores ortográficos o terminológicos en lenguaje clínico.
- **Procesar** y normalizar la consulta antes de la búsqueda semántica.

## Puerto

- **8003** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| POST | `/analyze` | Análisis de la consulta |
| POST | `/correct` | Corrección de la consulta |
| POST | `/process` | Procesado completo de la consulta |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `ID` | Identificador del proyecto de Google Cloud |
| `LOCATION` | Región de Vertex AI (por defecto `europe-west1`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Ruta al fichero de credenciales de servicio (montado como volumen) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

> ⚠️ El fichero de credenciales de Google Cloud **no** debe subirse al repositorio: se monta como
> volumen de solo lectura en tiempo de ejecución.

## Dependencias

FastAPI · Uvicorn · Pydantic · requests · google-cloud-aiplatform · google-auth
