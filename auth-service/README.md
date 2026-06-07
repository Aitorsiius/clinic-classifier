# Auth Service

Servicio de autenticación y gestión de usuarios. Emite y valida tokens JWT, almacena las
credenciales con *hash* bcrypt en MongoDB y expone las operaciones de administración de cuentas.

## Propósito

- Autenticar usuarios y generar tokens JWT (login, refresco y validación).
- Gestionar el ciclo de vida de las cuentas: registro, listado, cambio de rol, cambio de
  contraseña y eliminación (estas últimas restringidas a administradores).
- Proteger el inicio de sesión frente a ataques de fuerza bruta mediante *rate limiting*
  con bloqueo de cuenta y desbloqueo manual por un administrador.
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
| GET | `/admin/users/{username}/block-info` | Información de bloqueo: intentos fallidos y nº de bloqueos (admin) |
| POST | `/admin/users/{username}/unblock` | Desbloqueo de un usuario bloqueado (admin) |

## Rate limiting y bloqueo de inicio de sesión

Para mitigar ataques de fuerza bruta, el servicio aplica una política configurable sobre
`/auth/login` (ver módulo [`rate_limiter.py`](./rate_limiter.py)):

- Si un usuario falla el login varias veces (`LOGIN_MAX_FAILED_ATTEMPTS`) dentro de una ventana
  corta (`LOGIN_ATTEMPT_WINDOW_SECONDS`), su cuenta queda **bloqueada** y se registra la **IP**
  del equipo desde la que se realizaron los intentos.
- Mientras el bloqueo está activo, cualquier intento de login para esa cuenta se rechaza con
  **403** y un mensaje claro para el usuario.
- El bloqueo se aplica **por cuenta** (no es un baneo estricto por IP en el login) para no
  dejar fuera al administrador ni a otros usuarios legítimos que compartan IP (NAT, mismo
  equipo, red interna de Docker). La IP del atacante se guarda y se muestra al administrador
  como contexto forense (intentos fallidos con su IP y fecha).
- El bloqueo persiste hasta que un **administrador** lo revisa y desbloquea desde el panel de
  administración (`POST /admin/users/{username}/unblock`), lo que reinicia el contador.
- El listado de usuarios (`GET /admin/users`) incluye el campo `blocked` para señalar las
  cuentas bloqueadas en la interfaz.

La IP real del cliente la reenvía el API Gateway en las cabeceras `X-Forwarded-For` /
`X-Real-IP`. La persistencia se realiza en dos colecciones de MongoDB que identifican al
usuario **siempre por su `user_id`** (el `_id` opaco de MongoDB), nunca por el `username`: así,
mirando la base de datos no se revela a simple vista a qué usuario corresponde cada registro. La
traducción `username` ⇆ `user_id` la realiza el `auth-service`, de forma transparente para la
aplicación.

- `login_attempts`: un documento por intento fallido (`user_id`, `ip_address`, `user_agent`,
  `timestamp`).
- `login_blocks`: un documento por bloqueo (`user_id`, `ip_address`, `reason`, `blocked_at`,
  `active`, `unblocked_at`, `unblocked_by`). El historial permite contar cuántas veces ha sido
  bloqueado un mismo usuario.

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
| `LOGIN_MAX_FAILED_ATTEMPTS` | Intentos fallidos antes de bloquear (por defecto `5`) |
| `LOGIN_ATTEMPT_WINDOW_SECONDS` | Ventana en segundos para contar los intentos (por defecto `60`) |
| `HOST` | Interfaz de escucha (por defecto `0.0.0.0` para Docker) |

## Dependencias

FastAPI · Uvicorn · Pydantic · PyJWT · pymongo[srv] · bcrypt · httpx
