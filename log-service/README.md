# Log Service

Servicio centralizado de registro de actividad. Persiste en MongoDB las sesiones, búsquedas,
auditorías y acciones administrativas del sistema, sirviendo de base para trazabilidad y métricas.

## Propósito

- Registrar el ciclo de vida de las **sesiones** de usuario (apertura y cierre).
- Almacenar las **búsquedas** realizadas y enriquecerlas con metadatos de IA.
- Guardar los resultados de las **auditorías** de codificación.
- Auditar las **acciones administrativas** sobre usuarios.

## Puerto

- **8006** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| POST | `/sessions/create` · `/sessions/close` | Apertura y cierre de sesión |
| POST | `/searches` · PATCH `/searches/update-ai` | Registro y actualización de búsquedas |
| POST | `/audits` | Registro de auditorías |
| POST · GET | `/admin-actions` | Registro y consulta de acciones administrativas |
| GET | `/sessions` · `/searches` · `/audits` | Consulta de registros |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `MONGO_CONNECTION` | Cadena de conexión a MongoDB |
| `LOG_SERVICE_PORT` | Puerto de escucha (por defecto `8006`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · pymongo · python-dotenv · httpx
