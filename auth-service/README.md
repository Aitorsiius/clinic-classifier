# Auth Service

Servicio de autenticación y gestión de usuarios. Emite y valida tokens JWT, almacena las
credenciales con *hash* bcrypt en MongoDB y expone las operaciones de administración de cuentas.

## Propósito

- Autenticar usuarios y generar tokens JWT (login, refresco y validación).
- Gestionar el ciclo de vida de las cuentas: registro, listado, cambio de rol, cambio de
  contraseña y eliminación (estas últimas restringidas a administradores).
- Servir como fuente de verdad de la identidad para el resto de microservicios.

## Puerto

- **8004** (HTTP)

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del servicio |
| POST | `/auth/login` | Inicio de sesión y emisión de token |
| POST | `/auth/verify` · `/auth/refresh` | Verificación / refresco de token |
| GET | `/auth/validate-token` | Validación rápida del token |
| POST | `/auth/register` | Registro de usuario |
| GET · POST | `/admin/users` | Listado y creación de usuarios (admin) |
| PUT | `/admin/users/{username}/role` | Cambio de rol (admin) |
| PUT | `/admin/users/{username}/password` | Cambio de contraseña (admin) |
| DELETE | `/admin/users/{username}` | Eliminación de usuario (admin) |

## Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `JWT_SECRET` | Clave de firma JWT (**obligatoria**, sin valor por defecto) |
| `JWT_ALGORITHM` | Algoritmo JWT (por defecto `HS256`) |
| `JWT_EXPIRATION_HOURS` | Caducidad del token en horas (por defecto `24`) |
| `MONGO_CONNECTION` | Cadena de conexión a MongoDB |
| `LOG_SERVICE_URL` | URL del servicio de logs |
| `AUTH_SERVICE_PORT` | Puerto de escucha (por defecto `8004`) |
| `ALLOWED_ORIGINS` | Orígenes permitidos para CORS (separados por comas) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · PyJWT · pymongo[srv] · bcrypt · httpx
