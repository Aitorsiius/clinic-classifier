"""
Servicio de Autenticación - CIE-10 Classifier

Microservicio responsable de:
- Autenticación de usuarios (login)
- Generación y validación de tokens JWT
- Renovación de tokens
"""

from fastapi import FastAPI, HTTPException, Request, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import jwt
from datetime import datetime, timedelta, timezone
import os
import uvicorn
from typing import Optional, Annotated
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import bcrypt
import httpx
import logging

# ==========================================
# CONFIGURACIÓN
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    """Obtiene una variable de entorno obligatoria o aborta el arranque.

    Evita secretos por defecto incrustados en el código fuente forzando a definir el valor en el entorno.
    """
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"La variable de entorno '{name}' es obligatoria y no está definida. "
            "Defínela en el fichero .env antes de iniciar el servicio."
        )
    return value


JWT_SECRET = _require_env("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
AUTH_SERVICE_PORT = int(os.getenv("AUTH_SERVICE_PORT", "8004"))
# En contenedores debe ser 0.0.0.0 para aceptar conexiones del resto de
# servicios de la red interna de Docker; el acceso queda acotado por la red
# bridge aislada y por los puertos publicados en docker-compose.
HOST = os.getenv("HOST", "0.0.0.0")
MONGO_CONNECTION = os.getenv("MONGO_CONNECTION", "mongodb://localhost:27017/clinic-classifier")
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://localhost:8006")
# Orígenes permitidos para CORS (configurables por entorno). Por defecto solo
# el frontend local; nunca "*" junto con cookies/credenciales.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

# Mensajes de error reutilizados en varios endpoints
USER_NOT_FOUND_DETAIL = "User not found"

# ==========================================
# CONEXIÓN A MONGODB
# ==========================================
mongo_client = None
db = None
users_collection = None

def init_mongodb():
    """Inicializa la conexión a MongoDB"""
    global mongo_client, db, users_collection
    try:
        mongo_client = MongoClient(MONGO_CONNECTION, serverSelectionTimeoutMS=5000)
        # Verificar la conexión
        mongo_client.admin.command('ping')
        db = mongo_client.get_database('clinic-classifier')
        users_collection = db['users']
        logger.info("Conexión a MongoDB establecida correctamente")
        return True
    except ServerSelectionTimeoutError:
        logger.warning("No se pudo conectar a MongoDB. Se reintentará en los endpoints.")
        return False
    except Exception:
        logger.exception("Error al conectar a MongoDB")
        return False

# Intentar conexión inicial
init_mongodb()

# ==========================================
# MODELOS PYDANTIC
# ==========================================
class LoginRequest(BaseModel):
    """Solicitud de login"""
    username: str
    password: str

class LoginResponse(BaseModel):
    """Respuesta de login"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_data: dict

class User(BaseModel):
    """Modelo de usuario en la base de datos"""
    username: str
    password: str
    admin: bool = False
    audit: bool = False

class VerifyTokenRequest(BaseModel):
    """Solicitud para verificar token"""
    token: str

class VerifyTokenResponse(BaseModel):
    """Respuesta de verificación de token"""
    valid: bool
    username: Optional[str] = None
    expires_at: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    """Solicitud para renovar token"""
    token: str

class RefreshTokenResponse(BaseModel):
    """Respuesta de renovación de token"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UserResponse(BaseModel):
    """Respuesta con datos de usuario para admin"""
    username: str
    admin: bool
    audit: bool
    created_at: Optional[str] = None

class CreateUserRequest(BaseModel):
    """Solicitud para crear un nuevo usuario"""
    username: str
    password: str
    admin: bool = False
    audit: bool = False

class UpdateRoleRequest(BaseModel):
    """Solicitud para actualizar rol de usuario"""
    admin: bool
    audit: bool

class UpdatePasswordRequest(BaseModel):
    """Solicitud para cambiar contraseña"""
    new_password: str

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
def create_token(username: str, hours: Optional[int] = None) -> tuple[str, datetime]:
    """
    Crea un JWT token para el usuario
    
    Args:
        username: Username del usuario
        hours: Horas de expiración (usa la configuración global si no se especifica)
        
    Returns:
        Tupla de (token, datetime_expiracion)
    """
    if hours is None:
        hours = JWT_EXPIRATION_HOURS
        
    exp_time = datetime.now(timezone.utc) + timedelta(hours=hours)
    payload = {
        "username": username,
        "exp": exp_time,
        "iat": datetime.now(timezone.utc)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, exp_time

def verify_token(token: str) -> dict:
    """
    Verifica y decodifica un JWT token
    
    Args:
        token: Token JWT a verificar
        
    Returns:
        Diccionario con el payload del token
        
    Raises:
        HTTPException: Si el token es inválido o ha expirado
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def hash_password(password: str) -> str:
    """
    Hashea una contraseña usando bcrypt
    
    Args:
        password: Contraseña en texto plano
        
    Returns:
        Contraseña hasheada
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra su hash usando bcrypt
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Contraseña hasheada
        
    Returns:
        True si coinciden, False en otro caso
    """
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# ==========================================
# FUNCIONES DE MONGODB
# ==========================================
def get_user_by_username(username: str) -> Optional[dict]:
    """
    Obtiene un usuario de MongoDB por su username
    
    Args:
        username: Username del usuario
        
    Returns:
        Diccionario del usuario o None si no existe
    """
    try:
        # Reintentar conexión si no está disponible
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para obtener usuario")
            return None
            
        user = users_collection.find_one({"username": username})
        return user
    except Exception:
        logger.exception("Error al obtener usuario")
        return None

def create_user(username: str, password: str, admin: bool = False, audit: bool = False) -> bool:
    """
    Crea un nuevo usuario en MongoDB
    
    Args:
        username: Username del usuario
        password: Contraseña en texto plano
        admin: Si es administrador
        audit: Si es auditor
        
    Returns:
        True si se creó correctamente, False en caso contrario
    """
    try:
        # Reintentar conexión si no está disponible
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para crear usuario")
            return False
        
        # Verificar que el usuario no existe ya
        if get_user_by_username(username):
            return False
        
        hashed_password = hash_password(password)
        user_doc = {
            "username": username,
            "password": hashed_password,
            "admin": admin,
            "audit": audit,
            "created_at": datetime.now(timezone.utc)
        }
        result = users_collection.insert_one(user_doc)
        return result.inserted_id is not None
    except Exception:
        logger.exception("Error al crear usuario")
        return False

def get_user_data(user: dict) -> dict:
    """
    Extrae los datos públicos del usuario (sin contraseña)
    
    Args:
        user: Diccionario del usuario de MongoDB
        
    Returns:
        Diccionario con los datos públicos
    """
    return {
        "user_id": str(user.get("_id")),  # Convert MongoDB ObjectId to string
        "username": user.get("username"),
        "admin": user.get("admin", False),
        "audit": user.get("audit", False)
    }

def get_all_users() -> list:
    """
    Obtiene todos los usuarios de MongoDB
    
    Returns:
        Lista de usuarios sin sus contraseñas
    """
    try:
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para obtener usuarios")
            return []
        
        users = list(users_collection.find({}, {"password": 0}))
        # Convertir ObjectId a string para JSON serialization
        for user in users:
            if "_id" in user:
                user["_id"] = str(user["_id"])
            if "created_at" in user and user["created_at"]:
                user["created_at"] = user["created_at"].isoformat()
        return users
    except Exception:
        logger.exception("Error al obtener usuarios")
        return []

def update_user_roles(username: str, admin: bool, audit: bool) -> bool:
    """
    Actualiza los roles de un usuario
    
    Args:
        username: Username del usuario
        admin: Si es administrador
        audit: Si es auditor
        
    Returns:
        True si se actualizó correctamente
    """
    try:
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para actualizar roles de usuario")
            return False
        
        result = users_collection.update_one(
            {"username": username},
            {"$set": {"admin": admin, "audit": audit}}
        )
        return result.modified_count > 0 or result.matched_count > 0
    except Exception:
        logger.exception("Error al actualizar roles del usuario")
        return False

def update_user_password(username: str, new_password: str) -> bool:
    """
    Actualiza la contraseña de un usuario
    
    Args:
        username: Username del usuario
        new_password: Nueva contraseña en texto plano
        
    Returns:
        True si se actualizó correctamente
    """
    try:
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para actualizar contraseña")
            return False
        
        hashed_password = hash_password(new_password)
        result = users_collection.update_one(
            {"username": username},
            {"$set": {"password": hashed_password}}
        )
        return result.modified_count > 0 or result.matched_count > 0
    except Exception:
        logger.exception("Error al actualizar contraseña")
        return False

def delete_user(username: str) -> bool:
    """
    Elimina un usuario de MongoDB
    
    Args:
        username: Username del usuario a eliminar
        
    Returns:
        True si se eliminó correctamente
    """
    try:
        if users_collection is None:
            init_mongodb()
        
        if users_collection is None:
            logger.error("MongoDB no disponible para eliminar usuario")
            return False
        
        result = users_collection.delete_one({"username": username})
        return result.deleted_count > 0
    except Exception:
        logger.exception("Error al eliminar usuario")
        return False

def get_current_admin_user(token: str) -> Optional[str]:
    """
    Verifica que el token pertenece a un admin y retorna su username
    
    Args:
        token: Token JWT
        
    Returns:
        Username si es admin, None en otro caso
        
    Raises:
        HTTPException: Si el token es inválido
    """
    try:
        payload = verify_token(token)
        username = payload.get("username")
        
        if not username:
            return None
        
        user = get_user_by_username(username)
        if user and user.get("admin", False):
            return username
        
        return None
    except HTTPException:
        raise
    except Exception:
        return None


async def log_admin_action(
    action: str,
    actor_user_id: str,
    actor_username: Optional[str] = None,
    target_user_id: Optional[str] = None,
    target_username: Optional[str] = None,
    session_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
) -> None:
    """
    Registra una acción de administración sobre usuarios en el log-service
    (alta, cambio de rol, cambio de contraseña, baja) para trazabilidad total.

    Es "best-effort": si el log-service no está disponible, no interrumpe la
    operación principal; simplemente se registra una advertencia.
    """
    payload = {
        "action": action,
        "actor_user_id": actor_user_id,
        "actor_username": actor_username,
        "target_user_id": target_user_id,
        "target_username": target_username,
        "session_id": session_id,
        "ip_address": ip_address,
        "status": status,
        "details": details,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{LOG_SERVICE_URL}/admin-actions", json=payload)
    except Exception as e:
        logger.warning(f"No se pudo registrar la acción de admin '{action}': {e}")


def get_user_id(username: str) -> Optional[str]:
    """Obtiene el user_id (ObjectId en str) de un usuario por su username."""
    user = get_user_by_username(username)
    if user and user.get("_id") is not None:
        return str(user["_id"])
    return None


BEARER_PREFIX = "Bearer "


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extrae el token Bearer de la cabecera Authorization."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.replace(BEARER_PREFIX, "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    return token


def require_admin(authorization: Optional[str]) -> str:
    """Valida que la petición la realiza un administrador.

    Centraliza la autorización de administrador para evitar duplicar la lógica
    de seguridad en cada endpoint.

    Returns:
        El username del administrador autenticado.

    Raises:
        HTTPException: 401 si falta/!es inválido el token, 403 si no es admin.
    """
    token = _extract_bearer_token(authorization)
    admin_username = get_current_admin_user(token)
    if not admin_username:
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin_username


# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="Auth Service - CIE-10 Classifier",
    description="Microservicio de autenticación para CIE-10 Classifier",
    version="1.0.0"
)

# Configurar CORS (orígenes restringidos y configurables; nunca "*" con credenciales)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/health", tags=["Health"])
async def health_check():
    """Verificar que el servicio está funcionando"""
    return {
        "status": "healthy",
        "service": "auth-service",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login(request: LoginRequest, request_obj: Request):
    """
    Endpoint de login
    
    Args:
        request: Credenciales de login (username y password)
        request_obj: Request object para obtener IP
        
    Returns:
        LoginResponse con token JWT y datos del usuario
        
    Raises:
        HTTPException: Si las credenciales son inválidas
    """
    # Reintentar conexión a MongoDB si es necesario
    if users_collection is None:
        init_mongodb()
    
    if users_collection is None:
        raise HTTPException(status_code=503, detail="Database connection unavailable")
    
    # Obtener usuario de MongoDB
    user = get_user_by_username(request.username)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verificar contraseña
    if not verify_password(request.password, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Crear token
    token, exp_time = create_token(request.username)
    expires_in = int((exp_time - datetime.now(timezone.utc)).total_seconds())
    
    # Get user_id from MongoDB _id
    user_id = str(user.get("_id"))
    
    # Registrar login en log-service
    try:
        ip_address = request_obj.client.host if request_obj.client else "unknown"
        user_agent = request_obj.headers.get("user-agent", "unknown")
        
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{LOG_SERVICE_URL}/sessions/create",
                json={
                    "user_id": user_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent
                },
                timeout=5
            )
    except Exception as e:
        logger.warning(f"No se pudo registrar login en log-service: {e}")
    
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        user_data=get_user_data(user)
    )

@app.post("/auth/verify", response_model=VerifyTokenResponse, tags=["Authentication"])
async def verify(request: VerifyTokenRequest):
    """
    Endpoint para verificar la validez de un token
    
    Args:
        request: Token a verificar
        
    Returns:
        VerifyTokenResponse indicando si el token es válido
    """
    try:
        payload = verify_token(request.token)
        username = payload.get("username")
        exp = payload.get("exp")
        
        # Convertir timestamp Unix a datetime ISO
        exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
        exp_iso = exp_datetime.isoformat()
        
        return VerifyTokenResponse(
            valid=True,
            username=username,
            expires_at=exp_iso
        )
    except HTTPException:
        return VerifyTokenResponse(
            valid=False,
            username=None,
            expires_at=None
        )

@app.post("/auth/refresh", response_model=RefreshTokenResponse, tags=["Authentication"])
async def refresh(request: RefreshTokenRequest):
    """
    Endpoint para renovar un token
    
    Args:
        request: Token actual a renovar
        
    Returns:
        RefreshTokenResponse con nuevo token
        
    Raises:
        HTTPException: Si el token es inválido
    """
    # Verificar que el token actual sea válido
    payload = verify_token(request.token)
    username = payload.get("username")
    
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    # Crear nuevo token
    new_token, exp_time = create_token(username)
    expires_in = int((exp_time - datetime.now(timezone.utc)).total_seconds())
    
    return RefreshTokenResponse(
        access_token=new_token,
        token_type="bearer",
        expires_in=expires_in
    )

@app.get("/auth/validate-token", tags=["Authentication"])
async def validate_token(token: str):
    """
    Endpoint auxiliar para validar token (parámetro en query)
    
    Args:
        token: Token a validar
        
    Returns:
        Información del token si es válido
        
    Raises:
        HTTPException: Si el token es inválido
    """
    payload = verify_token(token)
    exp_datetime = datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
    return {
        "valid": True,
        "username": payload.get("username"),
        "expires_at": exp_datetime.isoformat()
    }

@app.post("/auth/register", tags=["Authentication"])
async def register(user: User):
    """
    Endpoint para registrar un nuevo usuario
    
    Args:
        user: Datos del usuario a crear
        
    Returns:
        Mensaje de éxito o error
        
    Raises:
        HTTPException: Si el usuario ya existe o hay error en la creación
    """
    if not create_user(user.username, user.password, user.admin, user.audit):
        raise HTTPException(status_code=400, detail="User already exists or error creating user")
    
    return {
        "message": "User created successfully",
        "username": user.username
    }

# ==========================================
# ENDPOINTS DE ADMINISTRACIÓN
# ==========================================

@app.get("/admin/users", response_model=list, tags=["Admin Management"])
async def list_users(authorization: Annotated[str | None, Header()] = None):
    """
    Lista todos los usuarios (solo admin)
    
    Args:
        authorization: Header de autorización con formato "Bearer <token>"
        
    Returns:
        Lista de usuarios
        
    Raises:
        HTTPException: Si no es admin o token es inválido
    """
    require_admin(authorization)

    users = get_all_users()
    return users

@app.post("/admin/users", response_model=dict, tags=["Admin Management"])
async def create_new_user(
    request: CreateUserRequest,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
    x_session_id: Annotated[str | None, Header()] = None,
):
    """
    Crea un nuevo usuario (solo admin)
    
    Args:
        request: Datos del nuevo usuario
        authorization: Header de autorización
        
    Returns:
        Datos del usuario creado
        
    Raises:
        HTTPException: Si no es admin o hay error en creación
    """
    admin_username = require_admin(authorization)

    # Validar que username no está vacío
    if not request.username or len(request.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    
    # Validar que password no está vacío
    if not request.password or len(request.password.strip()) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Crear usuario
    if not create_user(request.username, request.password, request.admin, request.audit):
        raise HTTPException(status_code=400, detail="User already exists or error creating user")
    
    user = get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=500, detail="Error retrieving created user")
    
    # Trazabilidad: registrar la creación del usuario
    background_tasks.add_task(
        log_admin_action,
        action="create_user",
        actor_user_id=get_user_id(admin_username) or admin_username,
        actor_username=admin_username,
        target_user_id=str(user.get("_id")),
        target_username=request.username,
        session_id=x_session_id,
        details={"admin": request.admin, "audit": request.audit},
    )

    return {
        "message": "User created successfully",
        "user": get_user_data(user)
    }

@app.put("/admin/users/{username}/role", response_model=dict, tags=["Admin Management"])
async def update_user_role(
    username: str,
    request: UpdateRoleRequest,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
    x_session_id: Annotated[str | None, Header()] = None,
):
    """
    Actualiza el rol de un usuario (solo admin)
    
    Args:
        username: Username del usuario a actualizar
        request: Nuevos roles (admin y audit)
        authorization: Header de autorización
        
    Returns:
        Datos del usuario actualizado
        
    Raises:
        HTTPException: Si no es admin o usuario no existe
    """
    admin_username = require_admin(authorization)

    # No se puede cambiar los roles del último admin
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND_DETAIL)
    
    if user.get("admin", False) and not request.admin:
        # Verificar que hay al menos otro admin
        all_users = get_all_users()
        admin_count = sum(1 for u in all_users if u.get("admin", False))
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove admin role from the last admin")
    
    # Actualizar roles
    if not update_user_roles(username, request.admin, request.audit):
        raise HTTPException(status_code=500, detail="Error updating user roles")
    
    updated_user = get_user_by_username(username)
    if not updated_user:
        raise HTTPException(status_code=500, detail="Error retrieving updated user")
    
    # Trazabilidad: registrar el cambio de rol (roles antiguos y nuevos)
    background_tasks.add_task(
        log_admin_action,
        action="update_role",
        actor_user_id=get_user_id(admin_username) or admin_username,
        actor_username=admin_username,
        target_user_id=str(user.get("_id")),
        target_username=username,
        session_id=x_session_id,
        details={
            "old_roles": {"admin": user.get("admin", False), "audit": user.get("audit", False)},
            "new_roles": {"admin": request.admin, "audit": request.audit},
        },
    )

    return {
        "message": "User roles updated successfully",
        "user": get_user_data(updated_user)
    }

@app.put("/admin/users/{username}/password", response_model=dict, tags=["Admin Management"])
async def change_user_password(
    username: str,
    request: UpdatePasswordRequest,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
    x_session_id: Annotated[str | None, Header()] = None,
):
    """
    Cambia la contraseña de un usuario (solo admin)
    
    Args:
        username: Username del usuario
        request: Nueva contraseña
        authorization: Header de autorización
        
    Returns:
        Mensaje de éxito
        
    Raises:
        HTTPException: Si no es admin o usuario no existe
    """
    admin_username = require_admin(authorization)

    # Verificar que el usuario existe
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND_DETAIL)
    
    # Validar nueva contraseña
    if not request.new_password or len(request.new_password.strip()) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Actualizar contraseña
    if not update_user_password(username, request.new_password):
        raise HTTPException(status_code=500, detail="Error updating password")
    
    # Trazabilidad: registrar el cambio de contraseña (sin almacenar la contraseña)
    background_tasks.add_task(
        log_admin_action,
        action="change_password",
        actor_user_id=get_user_id(admin_username) or admin_username,
        actor_username=admin_username,
        target_user_id=str(user.get("_id")),
        target_username=username,
        session_id=x_session_id,
    )

    return {
        "message": "Password updated successfully",
        "username": username
    }

@app.delete("/admin/users/{username}", response_model=dict, tags=["Admin Management"])
async def delete_existing_user(
    username: str,
    background_tasks: BackgroundTasks,
    authorization: Annotated[str | None, Header()] = None,
    x_session_id: Annotated[str | None, Header()] = None,
):
    """
    Elimina un usuario (solo admin)
    
    Args:
        username: Username del usuario a eliminar
        authorization: Header de autorización
        
    Returns:
        Mensaje de éxito
        
    Raises:
        HTTPException: Si no es admin o usuario no puede ser eliminado
    """
    admin_username = require_admin(authorization)

    # No se puede eliminar a sí mismo
    if username == admin_username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    # Verificar que el usuario existe
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail=USER_NOT_FOUND_DETAIL)
    
    # No se puede eliminar al último admin
    if user.get("admin", False):
        all_users = get_all_users()
        admin_count = sum(1 for u in all_users if u.get("admin", False))
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    
    # Eliminar usuario
    if not delete_user(username):
        raise HTTPException(status_code=500, detail="Error deleting user")
    
    # Trazabilidad: registrar la eliminación del usuario (con los roles que tenía)
    background_tasks.add_task(
        log_admin_action,
        action="delete_user",
        actor_user_id=get_user_id(admin_username) or admin_username,
        actor_username=admin_username,
        target_user_id=str(user.get("_id")),
        target_username=username,
        session_id=x_session_id,
        details={"admin": user.get("admin", False), "audit": user.get("audit", False)},
    )

    return {
        "message": "User deleted successfully",
        "username": username
    }

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=AUTH_SERVICE_PORT,
        log_level="info"
    )
