# API Gateway Service

Punto de entrada único del sistema. Centraliza las peticiones del frontend (`app`) y las
enruta hacia el resto de microservicios, encargándose de la verificación de tokens JWT, la
política CORS y la agregación de respuestas.

## Propósito

- Actuar como *reverse proxy* / orquestador entre el frontend y los servicios internos.
- Validar la autenticación (JWT) antes de delegar en los servicios protegidos.
- Reenviar las operaciones de búsqueda, auditoría, historial, administración y procesado con LLM.
- Propagar eventos de registro (logs) al `log-service`.

## Puerto

- **3000** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| POST | `/api/login` | Inicio de sesión (delegado en `auth-service`) |
| POST | `/api/logout` | Cierre de sesión |
| GET | `/api/verify-token` | Verificación de token |
| POST | `/api/search` | Búsqueda semántica de códigos CIE-10 |
| POST | `/api/audit/batch` · `/api/audit/batch-stream` | Auditoría por lotes (incl. streaming SSE) |
| POST | `/api/analyze-query` · `/api/correct-query` · `/api/process-query` | Procesado de consultas con LLM |
| GET | `/api/search-history` | Historial de búsquedas del usuario |
| `*` | `/api/admin/users...` | Gestión de usuarios (solo administradores) |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `BACKEND_URL` | URL del clasificador CIE-10 |
| `LLM_QUERY_PROCESSOR_URL` | URL del procesador de consultas LLM |
| `AUTH_SERVICE_URL` | URL del servicio de autenticación |
| `AUDIT_SERVICE_URL` | URL del servicio de auditoría |
| `LOG_SERVICE_URL` | URL del servicio de logs |
| `HISTORY_SERVICE_URL` | URL del servicio de historial |
| `JWT_SECRET` | Clave de firma JWT (obligatoria) |
| `JWT_ALGORITHM` | Algoritmo JWT (por defecto `HS256`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · httpx · Pydantic · PyJWT · python-multipart
