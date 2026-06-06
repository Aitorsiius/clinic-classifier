# Audit Service

Servicio de auditoría de codificación CIE-10. Procesa lotes de registros clínicos, compara el
código asignado con la recomendación del clasificador y genera un informe de discrepancias.

## Propósito

- Auditar por lotes las asignaciones de códigos CIE-10 frente a la búsqueda del sistema.
- Clasificar cada registro (coincidencia exacta, alternativa o discrepancia).
- Emitir el progreso en tiempo real mediante *Server-Sent Events* (SSE).
- Persistir los resultados de auditoría a través del `log-service`.

## Puerto

- **8005** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| POST | `/audit/batch-stream` | Auditoría por lotes con progreso vía SSE |
| POST | `/audit/batch` | Auditoría por lotes (respuesta única) |
| POST | `/audit/record` | Auditoría de un único registro |
| GET | `/audit/{audit_id}` | Recuperación de un informe de auditoría |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `API_GATEWAY_URL` | URL del API Gateway (origen de las búsquedas) |
| `LOG_SERVICE_URL` | URL del servicio de logs |
| `JWT_SECRET` | Clave de firma JWT |
| `JWT_ALGORITHM` | Algoritmo JWT (por defecto `HS256`) |
| `AUDIT_SERVICE_PORT` | Puerto de escucha (por defecto `8005`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · httpx
