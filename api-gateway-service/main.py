from fastapi import FastAPI, HTTPException, Request, Depends, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import httpx
import uvicorn
import os
import jwt
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import asyncio
import logging
from typing import Annotated
import urllib.parse

# ==========================================
# CONFIGURACIÓN
# ==========================================
# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = "data"


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

def _is_valid_cors_origin(origin: str) -> bool:
    """Valida que un origen CORS sea seguro y no contenga caracteres peligrosos."""
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    # Evitar caracteres peligrosos en el dominio
    if any(c in parsed.netloc for c in "<>\"'`"):
        return False
    return True


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
LLM_QUERY_PROCESSOR_URL = os.getenv("LLM_QUERY_PROCESSOR_URL", "http://localhost:8003")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8004")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://localhost:8005")
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://localhost:8006")
HISTORY_SERVICE_URL = os.getenv("HISTORY_SERVICE_URL", "http://localhost:8007")
JWT_SECRET = _require_env("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
# En contenedores debe ser 0.0.0.0 para aceptar conexiones del resto de
# servicios de la red interna de Docker; el acceso queda acotado por la red
# bridge aislada y por los puertos publicados en docker-compose.
HOST = os.getenv("HOST", "0.0.0.0")
# Orígenes permitidos para CORS (configurables por entorno). Por defecto solo
# el frontend local; nunca "*" junto con cookies/credenciales.
raw_origins = os.getenv("ALLOWED_ORIGINS", "https://localhost,https://localhost:3000")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in raw_origins.split(",")
    if origin.strip() and _is_valid_cors_origin(origin.strip())
]

# Mensaje genérico para respuestas 5xx: evita filtrar detalles internos
# (trazas, rutas, mensajes de excepción) al cliente.
INTERNAL_ERROR_DETAIL = "Internal server error"
# Mensajes por defecto al propagar errores del procesador de consultas LLM.
LLM_PROCESSOR_ERROR_DETAIL = "LLM processor error"
LLM_PROCESSOR_TIMEOUT_DETAIL = "LLM processor request timeout"
LLM_PROCESSOR_CONNECT_ERROR_DETAIL = "Cannot connect to LLM processor service"
# Mensajes reutilizados en los endpoints administrativos delegados al auth-service.
AUTH_HEADER_MISSING_DETAIL = "Authorization header missing"
ADMIN_ACCESS_REQUIRED_DETAIL = "Admin access required"
AUTH_SERVICE_UNAVAILABLE_DETAIL = "Auth service unavailable"

# ==========================================
# MODELOS PYDANTIC
# ==========================================
class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    # Activa el pipeline de búsqueda con IA (primera fase LLM + bi-encoder +
    # cross-encoder).
    use_ai: bool = False

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_data: dict
    session_id: Optional[str] = None

class TokenPayload(BaseModel):
    username: str
    exp: datetime

class AuditRecordRequest(BaseModel):
    diagnosis_text: str
    assigned_code: str
    patient_id: Optional[str] = None

class AuditBatchRequest(BaseModel):
    records: List[AuditRecordRequest]
    top_k: Optional[int] = 5
    algorithm: Optional[str] = "algoritmo1"
    # Ejecuta la auditoría a través del pipeline de búsqueda con IA.
    use_ai: bool = False

# ==========================================
# FUNCIONES DE AUTENTICACIÓN
# ==========================================
def create_token(username: str) -> str:
    """Crea un JWT token para el usuario autenticado"""
    payload = {
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def verify_token(token: str) -> dict:
    """Verifica y decodifica un JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(request: Request) -> str:
    """Dependency para obtener el usuario actual desde el token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid auth scheme")
        payload = verify_token(token)
        username = payload.get("username")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return username
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")

# ==========================================
# FUNCIONES DE LOGGING
# ==========================================

async def log_search(
    session_id: str,
    user_id: str,
    query: str,
    top_k: Optional[int] = None,
    results_count: int = 0,
    ip_address: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    details: Optional[dict] = None
):
    """
    Registra una búsqueda en el servicio de logs de forma no-bloqueante.
    """
    try:
        if not LOG_SERVICE_URL:
            logger.warning("LOG_SERVICE_URL no configurada")
            return
        
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{LOG_SERVICE_URL}/searches",
                json={
                    "session_id": session_id,
                    "user_id": user_id,
                    "query": query,
                    "top_k": top_k,
                    "results_count": results_count,
                    "ip_address": ip_address,
                    "description": "Search query performed",
                    "status": status,
                    "error_message": error_message,
                    "details": details
                },
                timeout=2.0
            )
    except asyncio.TimeoutError:
        logger.warning("Timeout al registrar búsqueda en el servicio de logs")
    except Exception as e:
        logger.warning(f"Error al registrar búsqueda: {e}")

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

async def log_audit(
    session_id: str,
    user_id: str,
    records_count: int,
    algorithm: Optional[str] = None,
    top_k: Optional[int] = None,
    use_ai: bool = False,
    total_time_ms: Optional[float] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    details: Optional[dict] = None
):
    """
    Registra una auditoría en el servicio de logs de forma no-bloqueante.
    """
    try:
        if not LOG_SERVICE_URL:
            logger.warning("LOG_SERVICE_URL no configurada")
            return
        
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{LOG_SERVICE_URL}/audits",
                json={
                    "session_id": session_id,
                    "user_id": user_id,
                    "records_count": records_count,
                    "algorithm": algorithm,
                    "top_k": top_k,
                    "use_ai": use_ai,
                    "total_time_ms": total_time_ms,
                    "ip_address": ip_address,
                    "description": f"Audit with {records_count} records",
                    "status": status,
                    "error_message": error_message,
                    "details": details
                },
                timeout=2.0
            )
    except asyncio.TimeoutError:
        logger.warning("Timeout al registrar auditoría en el servicio de logs")
    except Exception as e:
        logger.warning(f"Error al registrar auditoría: {e}")

def _extract_audit_result_from_sse(line: str) -> dict | None:
    """Extrae y devuelve el resultado final si el evento es de tipo 'complete'."""
    if not line.startswith(f"{DATA}: "):
        return None
        
    if '"type": "complete"' in line or '"type":"complete"' in line:
        try:
            # Reemplazamos solo la primera ocurrencia por seguridad
            data_str = line.replace(f"{DATA}: ", "", 1)
            event_data = json.loads(data_str)
            return event_data.get("result", {})
        except json.JSONDecodeError:
            logger.warning("No se pudo parsear el evento de finalización de auditoría")
            
    return None

async def _log_successful_audit(
    audit_result: dict, 
    request: AuditBatchRequest, 
    req: Request, 
    session_id: str | None, 
    user_id: str | None
):
    """Prepara y envía el log de la auditoría al servicio correspondiente."""
    if not (session_id and user_id and audit_result):
        return

    logger.info("Registrando auditoría con %d registros", len(request.records))
    
    details = {
        "audit_id": audit_result.get("audit_id"),
        "timestamp": audit_result.get("timestamp"),
        "total_records": audit_result.get("total_records"),
        "total_correct": audit_result.get("total_correct"),
        "total_partial_match": audit_result.get("total_partial_match"),
        "total_mismatch": audit_result.get("total_mismatch"),
        "conformity_percentage": audit_result.get("conformity_percentage"),
        "top_k": audit_result.get("top_k"),
        "algorithm": request.algorithm or "algoritmo1",
        "use_ai": request.use_ai,
        "total_time_ms": audit_result.get("total_time_ms"),
        "findings": audit_result.get("findings", [])
    }
    
    await log_audit(
        session_id=session_id,
        user_id=user_id,
        records_count=len(request.records),
        algorithm=request.algorithm or "algoritmo1",
        top_k=request.top_k or 5,
        use_ai=request.use_ai,
        total_time_ms=audit_result.get("total_time_ms"),
        ip_address=get_client_ip(req) if req else "unknown",
        status="success",
        details=details
    )

async def _fetch_backend_stream(payload: dict, auth_header: str):
    """Maneja exclusivamente la conexión HTTPX y el stream de datos crudos."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            f"{AUDIT_SERVICE_URL}/audit/batch-stream",
            json=payload,
            headers={"Authorization": auth_header}
        ) as response:
            
            if response.status_code != 200:
                yield "ERROR_STATUS"
                return
                
            async for line in response.aiter_lines():
                yield line

async def _audit_event_generator(
    payload: dict, auth_header: str, request: AuditBatchRequest, 
    req: Request, session_id: str | None, user_id: str | None
):
    """Consume el stream del backend, reenvía al cliente y lanza el log final."""
    audit_result = None
    try:
        async for line in _fetch_backend_stream(payload, auth_header):
            
            if line == "ERROR_STATUS":
                yield f'{DATA}: {{"type": "error", "message": "Audit service error"}}\n\n'
                return
                
            if not line.startswith(f"{DATA}: "):
                continue
                
            yield line + "\n\n"
            
            extracted = _extract_audit_result_from_sse(line)
            if extracted:
                audit_result = extracted
                
        if audit_result:
            await _log_successful_audit(audit_result, request, req, session_id, user_id)
            
    except httpx.TimeoutException:
        yield f'{DATA}: {{"type": "error", "message": "Request timeout"}}\n\n'
    except httpx.ConnectError:
        yield f'{DATA}: {{"type": "error", "message": "Cannot connect to audit service"}}\n\n'
    except Exception as e:
        logger.exception("Error durante el streaming de auditoría: %s", e)
        yield f'{DATA}: {{"type": "error", "message": "Internal server error"}}\n\n'

def get_client_ip(request: Request) -> str:
    """Obtiene la IP del cliente desde el request"""
    if request.client:
        return request.client.host
    return "unknown"

# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="API Gateway - CIE-10 Classifier",
    description="Gateway para comunicación entre frontend y backend del clasificador CIE-10",
    version="1.0.0"
)

# Configuración CORS (orígenes restringidos y configurables; nunca "*" con credenciales)
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
@app.get("/")
async def root():
    """Endpoint raíz del API Gateway"""
    return {
        "service": "API Gateway - CIE-10 Classifier",
        "status": "running",
        "version": "1.0.0",
        "backend_url": BACKEND_URL
    }

@app.get("/health")
async def health_check():
    """Verifica la salud del gateway, backend y LLM processor"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            backend_status = response.json()
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{LLM_QUERY_PROCESSOR_URL}/health")
                llm_status = response.json()
        except Exception as e:
            llm_status = {"status": f"unhealthy - {str(e)}"}
        
        return {
            "gateway": "healthy",
            "backend": backend_status,
            "llm_processor": llm_status
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "gateway": "healthy",
                "backend": f"unhealthy - {str(e)}"
            }
        )

@app.post("/api/login", response_model=LoginResponse, responses={401: {"description": "Invalid credentials"}, 
                                                                 503: {"description": "Auth service unavailable"}, 
                                                                 500: {"description": "Internal server error"}})
async def login(request: LoginRequest, req: Request):
    """
    Endpoint de login para usuarios - DELEGADO AL AUTH SERVICE
    
    Args:
        request: Credenciales (username y password)
        req: Request object para obtener IP
    
    Returns:
        JWT token con información de expiración y datos del usuario
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/auth/login",
                json={
                    "username": request.username,
                    "password": request.password
                },
                # Reenviar la IP real del cliente para que el auth-service pueda
                # aplicar el rate limiting / bloqueo por IP. Se usa la IP del
                # socket (no una cabecera proporcionada por el cliente), evitando
                # así que un atacante falsee su IP.
                headers={
                    "X-Forwarded-For": get_client_ip(req),
                    "X-Real-IP": get_client_ip(req),
                }
            )
        
        if response.status_code == 401:
            error_data = response.json()
            detail = error_data.get("detail", "Credenciales inválidas")
            # Asegurar que el mensaje sea legible sin códigos HTTP
            if detail.startswith("401:"):
                detail = detail[4:].strip()
            raise HTTPException(status_code=401, detail=detail)
        elif response.status_code != 200:
            error_data = response.json()
            detail = error_data.get("detail", "Login fallido")
            # Asegurar que el mensaje sea legible sin códigos HTTP
            if detail.startswith(f"{response.status_code}:"):
                detail = detail.split(":", 1)[1].strip()
            raise HTTPException(status_code=response.status_code, detail=detail)
        
        login_response = response.json()
        
        # Crear sesión en el servicio de logs de forma asíncrona
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                session_response = await client.post(
                    f"{LOG_SERVICE_URL}/sessions/create",
                    json={
                        "user_id": login_response.get("user_data", {}).get("user_id"),
                        "ip_address": get_client_ip(req),
                        "user_agent": req.headers.get("user-agent")
                    },
                    timeout=2.0
                )
                if session_response.status_code == 200:
                    session_data = session_response.json()
                    # Agregar session_id a la respuesta de login
                    login_response["session_id"] = session_data.get("session_id")
        except Exception as e:
            logger.warning(f"Error creating log session: {e}")
            # No fallar el login si hay error en logs
            login_response["session_id"] = "unknown"
        
        return login_response
    
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Servicio de autenticación no disponible")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Error en la autenticación")

@app.post("/api/logout")
async def logout(
    req: Request,
    user_username: Annotated[str, Depends(get_current_user)],
    session_id: Annotated[str | None, Query()] = None
):
    """
    Endpoint de logout para usuarios
    
    Returns:
        Mensaje de confirmación
    """
    # Cerrar la sesión en el servicio de logs de forma asíncrona
    if session_id:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"{LOG_SERVICE_URL}/sessions/close",
                    json={"session_id": session_id},
                    timeout=2.0
                )
        except Exception as e:
            logger.warning(f"Error closing log session: {e}")
    
    return {"message": f"User {user_username} logged out successfully"}

@app.get("/api/verify-token")
async def verify_token_endpoint(user_username: Annotated[str, Depends(get_current_user)]):
    """
    Verifica si el token actual es válido
    
    Returns:
        Información del usuario autenticado
    """
    return {"username": user_username, "status": "valid"}

@app.post("/auth/verify", responses={400: {"description": "Token required"}, 401: {"description": "Invalid token"}})
async def auth_verify(request: dict):
    """
    Endpoint para verificar tokens JWT - Delegado a Auth Service
    
    Usado por servicios internos (como audit-service) para validar tokens
    
    Args:
        request: Diccionario con el campo "token"
    
    Returns:
        Información de validación del token
    """
    token = request.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token required")
    
    try:
        # Verificar el token localmente en el gateway
        payload = verify_token(token)
        return {
            "valid": True,
            "username": payload.get("username"),
            "exp": payload.get("exp")
        }
    except HTTPException:
        return {
            "valid": False,
            "detail": "Invalid token"
        }

@app.post("/api/audit/batch", responses={400: {"description": "At least one record is required"}, 
                                         500: {"description": "Internal server error"}, 
                                         503: {"description": "Cannot connect to audit service"}, 
                                         504: {"description": "Audit request timeout"}})
async def audit_batch(
    req: Request,
    request: AuditBatchRequest,
    user_username: Annotated[str, Depends(get_current_user)],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
):
    """
    Endpoint para auditar un lote de diagnósticos - DELEGADO AL AUDIT SERVICE
    
    Args:
        request: Lote de registros a auditar
        user_username: Username del usuario autenticado (inyectado por dependency)
        session_id: ID de sesión (opcional, para logging)
        user_id: ID del usuario (opcional, para logging)
        req: Request object para obtener IP
    
    Returns:
        Reporte de auditoría con hallazgos
    """
    if not request.records:
        raise HTTPException(
            status_code=400,
            detail="At least one record is required"
        )
    
    try:
        # Obtener session_id y user_id del header si no están en params
        if not session_id:
            session_id = req.headers.get("x-session-id")
        if not user_id:
            user_id = req.headers.get("x-user-id")
        # Obtener token del auditor para pasar al audit service
        auth_header = f"Bearer {create_token(user_username)}"
        
        # Enviar solicitud al audit-service
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{AUDIT_SERVICE_URL}/audit/batch",
                json={
                    "records": [r.model_dump() for r in request.records],
                    "top_k": request.top_k or 5,
                    "algorithm": request.algorithm or "algoritmo1",
                    "use_ai": request.use_ai
                },
                headers={"Authorization": auth_header}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "Audit failed")
                )
            
            result = response.json()
            # Agregar información del usuario al reporte
            result["user_username"] = user_username
            
            # Registrar la auditoría de forma asincrónica
            if session_id and user_id:
                await log_audit(
                            session_id=session_id,
                            user_id=user_id,
                            records_count=len(request.records),
                            algorithm=request.algorithm,
                            top_k=request.top_k,
                            use_ai=request.use_ai,
                            total_time_ms=result.get("total_time_ms"),
                            ip_address=get_client_ip(req) if req else "unknown",
                            status="success",
                            details={
                                "records_count": len(request.records),
                                "top_k": request.top_k,
                                "algorithm": request.algorithm,
                                "use_ai": request.use_ai,
                                "total_time_ms": result.get("total_time_ms")
                            }
                        )
            
            return result
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Audit request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to audit service"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en el proxy de auditoría: %s", e)
        raise HTTPException(
            status_code=500,
            detail=INTERNAL_ERROR_DETAIL
        )

@app.post("/api/audit/batch-stream", responses={400: {"description": "At least one record is required"}})
async def audit_batch_stream(
    req: Request,
    request: AuditBatchRequest,
    user_username: Annotated[str, Depends(get_current_user)],
    session_id: str | None = None,
    user_id: str | None = None
):
    """Endpoint para auditar un lote de diagnósticos con streaming de progreso"""
    
    if not request.records:
        raise HTTPException(status_code=400, detail="At least one record is required")
        
    session_id = session_id or req.headers.get("x-session-id")
    user_id = user_id or req.headers.get("x-user-id")
    
    payload = {
        "records": [r.model_dump() for r in request.records],
        "top_k": request.top_k or 5,
        "algorithm": request.algorithm or "algoritmo1",
        "use_ai": request.use_ai
    }
    
    auth_header = f"Bearer {create_token(user_username)}"
    
    # Se lo damos todo mascado al generador externo
    generator = _audit_event_generator(
        payload, auth_header, request, req, session_id, user_id
    )
    
    return StreamingResponse(generator, media_type="text/event-stream")

@app.post("/api/search", responses={504: {"description": "Backend request timeout"},
                                    503: {"description": "Cannot connect to backend service"},
                                    500: {"description": "Internal server error"}})
async def search_diagnosis(
    req: Request,
    request: SearchRequest,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
):
    """
    Proxy para el endpoint de búsqueda del backend
    
    Args:
        request: Objeto con la query y top_k opcional
        session_id: ID de sesión (opcional, para logging)
        user_id: ID del usuario (opcional, para logging)
        req: Request object para obtener IP
    
    Returns:
        Resultados de búsqueda del backend
    """
    try:
        # Obtener session_id y user_id del header si no están en params
        if not session_id:
            session_id = req.headers.get("x-session-id")
        if not user_id:
            user_id = req.headers.get("x-user-id")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BACKEND_URL}/search",
                json=request.model_dump(),
                headers={
                    "x-session-id": session_id or "",
                    "x-user-id": user_id or ""
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "Backend error")
                )
            
            result = response.json()
            
            # Nota: El backend ya registra las búsquedas en el log-service
            # No duplicamos el registro aquí
            
            return result
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Backend request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to backend service"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en el proxy de búsqueda: %s", e)
        raise HTTPException(
            status_code=500,
            detail=INTERNAL_ERROR_DETAIL
        )

# Endpoint alternativo para compatibilidad
@app.post("/search", responses={504: {"description": "Backend request timeout"},
                                503: {"description": "Cannot connect to backend service"},
                                500: {"description": "Internal server error"}})
async def search_diagnosis_alt(request: SearchRequest):
    """Alias del endpoint de búsqueda"""
    return await search_diagnosis(request)

# ==========================================
# ENDPOINTS DEL PROCESADOR DE QUERIES LLM
# ==========================================
async def _proxy_llm_query(endpoint: str, query: str, timeout_seconds: float, log_label: str):
    """
    Reenvía una consulta al procesador LLM y normaliza los errores de transporte.

    Args:
        endpoint: Ruta del procesador LLM (p. ej. "/analyze").
        query: Texto de la consulta a procesar.
        timeout_seconds: Tiempo máximo de espera en segundos.
        log_label: Etiqueta del endpoint para los mensajes de log.

    Returns:
        Respuesta JSON del procesador LLM.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{LLM_QUERY_PROCESSOR_URL}{endpoint}",
                json={"query": query}
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", LLM_PROCESSOR_ERROR_DETAIL)
                )

            return response.json()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=LLM_PROCESSOR_TIMEOUT_DETAIL
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=LLM_PROCESSOR_CONNECT_ERROR_DETAIL
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error en el proxy %s: %s", log_label, e)
        raise HTTPException(
            status_code=500,
            detail=INTERNAL_ERROR_DETAIL
        )


@app.post("/api/analyze-query", responses={504: {"description": LLM_PROCESSOR_TIMEOUT_DETAIL},
                                           503: {"description": LLM_PROCESSOR_CONNECT_ERROR_DETAIL},
                                           500: {"description": INTERNAL_ERROR_DETAIL}})
async def analyze_query(request: SearchRequest):
    """
    Analiza una consulta para extraer síntomas y hallazgos clave usando LLM

    Args:
        request: Objeto con la query

    Returns:
        Análisis de la consulta
    """
    return await _proxy_llm_query("/analyze", request.query, 60.0, "analyze-query")


@app.post("/api/correct-query", responses={504: {"description": LLM_PROCESSOR_TIMEOUT_DETAIL},
                                           503: {"description": LLM_PROCESSOR_CONNECT_ERROR_DETAIL},
                                           500: {"description": INTERNAL_ERROR_DETAIL}})
async def correct_query(request: SearchRequest):
    """
    Corrige y normaliza una consulta

    Args:
        request: Objeto con la query

    Returns:
        Consulta corregida y normalizada
    """
    return await _proxy_llm_query("/correct", request.query, 60.0, "correct-query")


@app.post("/api/process-query", responses={504: {"description": LLM_PROCESSOR_TIMEOUT_DETAIL},
                                           503: {"description": LLM_PROCESSOR_CONNECT_ERROR_DETAIL},
                                           500: {"description": INTERNAL_ERROR_DETAIL}})
async def process_query(request: SearchRequest):
    """
    Pipeline completo: Análisis + Corrección

    Args:
        request: Objeto con la query

    Returns:
        Consulta procesada completamente con análisis
    """
    return await _proxy_llm_query("/process", request.query, 120.0, "process-query")

@app.patch("/api/log/update-ai")
async def update_ai_analysis(body: dict):
    """
    Actualiza los datos de análisis de IA en el log-service.
    Se llama desde el frontend después de obtener el análisis de IA.
    
    Args:
        body: Contiene session_id, query y ai_analysis
    
    Returns:
        Confirma la actualización
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(
                f"{LOG_SERVICE_URL}/searches/update-ai",
                json={
                    "session_id": body.get("session_id"),
                    "query": body.get("query"),
                    "ai_analysis": body.get("ai_analysis")
                }
            )
            
            if response.status_code not in [200, 204]:
                logger.warning(f"Log service AI update failed: {response.status_code}")
                # No levantamos error, solo log warning
                return {"status": "warning", "message": "AI analysis update failed"}
            
            return response.json()
            
    except httpx.TimeoutException:
        logger.warning("Log service AI update timeout")
        return {"status": "warning", "message": "Log service timeout"}
    except httpx.ConnectError:
        logger.warning("Cannot connect to log service")
        return {"status": "warning", "message": "Cannot connect to log service"}
    except Exception:
        logger.exception("Gateway error updating AI analysis")
        return {"status": "warning", "message": "Internal error updating AI analysis"}

# ==========================================
# ENDPOINTS DE ADMINISTRACIÓN
# ==========================================

async def _proxy_admin_request(
    request: Request,
    method: str,
    path: str,
    error_detail: str,
    log_label: str,
    body: Optional[dict] = None,
    forward_session: bool = False,
):
    """
    Reenvía una petición administrativa al auth-service preservando la
    autorización del cliente y normalizando los errores comunes.

    Args:
        request: Request original del cliente (para extraer cabeceras).
        method: Método HTTP a usar contra el auth-service.
        path: Ruta del auth-service (p. ej. "/admin/users").
        error_detail: Mensaje por defecto si el auth-service devuelve error.
        log_label: Texto para el log en caso de error inesperado.
        body: Cuerpo JSON a reenviar (opcional).
        forward_session: Si se debe propagar la cabecera x-session-id.

    Returns:
        Respuesta JSON del auth-service.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail=AUTH_HEADER_MISSING_DETAIL)

    forward_headers = {"Authorization": auth_header}
    if forward_session:
        session_id = request.headers.get("x-session-id")
        if session_id:
            forward_headers["x-session-id"] = session_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method,
                f"{AUTH_SERVICE_URL}{path}",
                json=body,
                headers=forward_headers,
            )

        if response.status_code == 403:
            raise HTTPException(status_code=403, detail=ADMIN_ACCESS_REQUIRED_DETAIL)
        if response.status_code != 200:
            error_data = response.json()
            raise HTTPException(
                status_code=response.status_code,
                detail=error_data.get("detail", error_detail),
            )

        return response.json()

    except httpx.RequestError:
        raise HTTPException(status_code=503, detail=AUTH_SERVICE_UNAVAILABLE_DETAIL)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("%s: %s", log_label, e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)


@app.get("/api/admin/users", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                        503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                        500: {"description": INTERNAL_ERROR_DETAIL}, 
                                        401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_list_users(request: Request):
    """
    Lista todos los usuarios (solo admin) - DELEGADO AL AUTH SERVICE
    """
    return await _proxy_admin_request(
        request,
        "GET",
        "/admin/users",
        error_detail="Error fetching users",
        log_label="Error listando usuarios (admin)",
    )

@app.post("/api/admin/users", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                         503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                         500: {"description": INTERNAL_ERROR_DETAIL},
                                         401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_create_user(request: Request, body: Annotated[dict, Body(...)]):
    """
    Crea un nuevo usuario (solo admin) - DELEGADO AL AUTH SERVICE
    """
    return await _proxy_admin_request(
        request,
        "POST",
        "/admin/users",
        error_detail="Error creating user",
        log_label="Error creando usuario (admin)",
        body=body,
        forward_session=True,
    )

@app.put("/api/admin/users/{username}/role", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                                       503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                                       500: {"description": INTERNAL_ERROR_DETAIL},
                                                       401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_update_user_role(username: str, request: Request, body: Annotated[dict, Body(...)]):
    """
    Actualiza los roles de un usuario (solo admin) - DELEGADO AL AUTH SERVICE
    """
    safe_username = urllib.parse.quote(username, safe="")
    return await _proxy_admin_request(
        request,
        "PUT",
        f"/admin/users/{safe_username}/role",
        error_detail="Error updating user roles",
        log_label="Error actualizando roles de usuario (admin)",
        body=body,
        forward_session=True,
    )

@app.put("/api/admin/users/{username}/password", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                                            503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                                            500: {"description": INTERNAL_ERROR_DETAIL},
                                                            401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_change_password(username: str, request: Request, body: Annotated[dict, Body(...)]):
    """
    Cambia la contraseña de un usuario (solo admin) - DELEGADO AL AUTH SERVICE
    """
    safe_username = urllib.parse.quote(username, safe="")
    return await _proxy_admin_request(
        request,
        "PUT",
        f"/admin/users/{safe_username}/password",
        error_detail="Error updating password",
        log_label="Error actualizando contraseña de usuario (admin)",
        body=body,
        forward_session=True,
    )

@app.delete("/api/admin/users/{username}", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                                      503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                                      500: {"description": INTERNAL_ERROR_DETAIL},
                                                      401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_delete_user(username: str, request: Request, user_username: Annotated[str, Depends(get_current_user)]):
    """
    Elimina un usuario (solo admin) - DELEGADO AL AUTH SERVICE
    """
    safe_username = urllib.parse.quote(username, safe="")
    return await _proxy_admin_request(
        request,
        "DELETE",
        f"/admin/users/{safe_username}",
        error_detail="Error deleting user",
        log_label="Error eliminando usuario (admin)",
        forward_session=True,
    )

@app.get("/api/admin/users/{username}/block-info", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                                               503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                                               500: {"description": INTERNAL_ERROR_DETAIL},
                                                               401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_user_block_info(username: str, request: Request):
    """
    Obtiene la información de bloqueo de un usuario (solo admin) - DELEGADO AL AUTH SERVICE

    Devuelve los intentos de inicio de sesión fallidos con sus fechas y el
    número de veces que el usuario ha sido bloqueado.
    """
    safe_username = urllib.parse.quote(username, safe="")
    return await _proxy_admin_request(
        request,
        "GET",
        f"/admin/users/{safe_username}/block-info",
        error_detail="Error fetching block info",
        log_label="Error obteniendo información de bloqueo (admin)",
    )

@app.post("/api/admin/users/{username}/unblock", responses={403: {"description": ADMIN_ACCESS_REQUIRED_DETAIL},
                                                            503: {"description": AUTH_SERVICE_UNAVAILABLE_DETAIL},
                                                            500: {"description": INTERNAL_ERROR_DETAIL},
                                                            401: {"description": AUTH_HEADER_MISSING_DETAIL}})
async def admin_unblock_user(username: str, request: Request):
    """
    Desbloquea a un usuario bloqueado por intentos fallidos (solo admin) - DELEGADO AL AUTH SERVICE
    """
    safe_username = urllib.parse.quote(username, safe="")
    return await _proxy_admin_request(
        request,
        "POST",
        f"/admin/users/{safe_username}/unblock",
        error_detail="Error unblocking user",
        log_label="Error desbloqueando usuario (admin)",
        forward_session=True,
    )

# ==========================================
# ENDPOINTS DE HISTORIAL
# ==========================================
@app.get("/api/search-history", responses={401: {"description": AUTH_HEADER_MISSING_DETAIL},
                                           503: {"description": "History service unavailable"},
                                           504: {"description": "History service request timeout"},
                                           500: {"description": INTERNAL_ERROR_DETAIL}})
async def get_user_search_history(request: Request, limit: int = 100):
    """
    Obtiene el historial de búsquedas del usuario actual,
    segmentado temporalmente - DELEGADO AL HISTORY SERVICE
    
    Args:
        request: Request object
        limit: Límite de búsquedas a retornar
    
    Returns:
        Historial segmentado de búsquedas
    """
    try:
        # Obtener el header de autorización original del cliente
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail=AUTH_HEADER_MISSING_DETAIL)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{HISTORY_SERVICE_URL}/history",
                params={"limit": limit},
                headers={"Authorization": auth_header}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Error fetching search history"
                )
            
            return response.json()
    
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="History service request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to history service"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error obteniendo historial de búsquedas: %s", e)
        raise HTTPException(
            status_code=500,
            detail=INTERNAL_ERROR_DETAIL
        )

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=3000,
        reload=False
    )
