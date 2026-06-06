# History Service

Servicio de historial de búsquedas por usuario. Consulta los registros almacenados para ofrecer
a cada usuario su actividad reciente de búsqueda de códigos CIE-10.

## Propósito

- Proporcionar el historial de búsquedas asociado a cada usuario.
- Exponer recuentos y listados recientes para la interfaz del frontend.
- Reutilizar los datos persistidos (MongoDB) protegiendo el acceso mediante JWT.

## Puerto

- **8007** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| GET | `/history` | Historial de búsquedas del usuario |
| GET | `/history/count` | Número total de búsquedas |
| GET | `/history/recent` | Últimas búsquedas realizadas |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `MONGO_CONNECTION` | Cadena de conexión a MongoDB |
| `JWT_SECRET` | Clave de firma JWT (obligatoria) |
| `JWT_ALGORITHM` | Algoritmo JWT (por defecto `HS256`) |
| `HISTORY_SERVICE_PORT` | Puerto de escucha (por defecto `8007`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · pymongo · PyJWT
