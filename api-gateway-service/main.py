from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import httpx
import uvicorn
import os
import jwt
from datetime import datetime, timedelta, timezone
from functools import lru_cache

# ==========================================
# CONFIGURACIÓN
# ==========================================
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
LLM_QUERY_PROCESSOR_URL = os.getenv("LLM_QUERY_PROCESSOR_URL", "http://localhost:8003")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8004")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://localhost:8005")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", 24))

# ==========================================
# MODELOS PYDANTIC
# ==========================================
class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class TokenPayload(BaseModel):
    email: str
    exp: datetime

class AuditRecordRequest(BaseModel):
    diagnosis_text: str
    assigned_code: str
    patient_id: Optional[str] = None

class AuditBatchRequest(BaseModel):
    records: List[AuditRecordRequest]
    top_k: Optional[int] = 5
    algorithm: Optional[str] = "algoritmo1"

# ==========================================
# FUNCIONES DE AUTENTICACIÓN
# ==========================================
def create_token(email: str) -> str:
    """Crea un JWT token para el usuario autenticado"""
    payload = {
        "email": email,
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
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return email
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="API Gateway - CIE-10 Classifier",
    description="Gateway para comunicación entre frontend y backend del clasificador CIE-10",
    version="1.0.0"
)

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Endpoint de login para usuarios - DELEGADO AL AUTH SERVICE
    
    Args:
        request: Credenciales (email y password)
    
    Returns:
        JWT token con información de expiración
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{AUTH_SERVICE_URL}/auth/login",
                json={
                    "email": request.email,
                    "password": request.password
                }
            )
        
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Login failed")
        
        return response.json()
    
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/logout")
async def logout(user_email: str = Depends(get_current_user)):
    """
    Endpoint de logout para usuarios
    
    Returns:
        Mensaje de confirmación
    """
    return {"message": f"User {user_email} logged out successfully"}

@app.get("/api/verify-token")
async def verify_token_endpoint(user_email: str = Depends(get_current_user)):
    """
    Verifica si el token actual es válido
    
    Returns:
        Información del usuario autenticado
    """
    return {"email": user_email, "status": "valid"}

@app.post("/auth/verify")
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
            "email": payload.get("email"),
            "exp": payload.get("exp")
        }
    except HTTPException:
        return {
            "valid": False,
            "detail": "Invalid token"
        }

@app.post("/api/audit/batch")
async def audit_batch(
    request: AuditBatchRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Endpoint para auditar un lote de diagnósticos - DELEGADO AL AUDIT SERVICE
    
    Args:
        request: Lote de registros a auditar
        user_email: Email del usuario autenticado (inyectado por dependency)
    
    Returns:
        Reporte de auditoría con hallazgos
    """
    if not request.records:
        raise HTTPException(
            status_code=400,
            detail="At least one record is required"
        )
    
    try:
        # Obtener token del auditor para pasar al audit service
        auth_header = f"Bearer {create_token(user_email)}"
        
        # Enviar solicitud al audit-service
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{AUDIT_SERVICE_URL}/audit/batch",
                json={
                    "records": [r.model_dump() for r in request.records],
                    "top_k": request.top_k or 5,
                    "algorithm": request.algorithm or "algoritmo1"
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
            result["user_email"] = user_email
            
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
        raise HTTPException(
            status_code=500,
            detail=f"Audit error: {str(e)}"
        )

@app.post("/api/audit/batch-stream")
async def audit_batch_stream(
    request: AuditBatchRequest,
    user_email: str = Depends(get_current_user)
):
    """
    Endpoint para auditar un lote de diagnósticos con streaming de progreso - DELEGADO AL AUDIT SERVICE
    
    Args:
        request: Lote de registros a auditar
        user_email: Email del auditor autenticado (inyectado por dependency)
    
    Yields:
        Eventos SSE con progreso y resultado final
    """
    if not request.records:
        raise HTTPException(
            status_code=400,
            detail="At least one record is required"
        )
    
    async def stream_audit():
        try:
            # Obtener token del auditor para pasar al audit service
            auth_header = f"Bearer {create_token(user_email)}"
            
            # Enviar solicitud al audit-service
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{AUDIT_SERVICE_URL}/audit/batch-stream",
                    json={
                        "records": [r.model_dump() for r in request.records],
                        "top_k": request.top_k or 5,
                        "algorithm": request.algorithm or "algoritmo1"
                    },
                    headers={"Authorization": auth_header}
                ) as response:
                    if response.status_code != 200:
                        yield "data: {\"type\": \"error\", \"message\": \"Audit service error\"}\n\n"
                        return
                    
                    # Pasar el stream directo del backend
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            yield line + "\n\n"
                        
        except httpx.TimeoutException:
            yield "data: {\"type\": \"error\", \"message\": \"Request timeout\"}\n\n"
        except httpx.ConnectError:
            yield "data: {\"type\": \"error\", \"message\": \"Cannot connect to audit service\"}\n\n"
        except Exception as e:
            yield f"data: {{\"type\": \"error\", \"message\": \"{str(e)}\"}}\n\n"
    
    return StreamingResponse(stream_audit(), media_type="text/event-stream")

@app.post("/api/search")
async def search_diagnosis(request: SearchRequest):
    """
    Proxy para el endpoint de búsqueda del backend
    
    Args:
        request: Objeto con la query y top_k opcional
    
    Returns:
        Resultados de búsqueda del backend
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BACKEND_URL}/search",
                json=request.dict()
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "Backend error")
                )
            
            return response.json()
            
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
        raise HTTPException(
            status_code=500,
            detail=f"Gateway error: {str(e)}"
        )

# Endpoint alternativo para compatibilidad
@app.post("/search")
async def search_diagnosis_alt(request: SearchRequest):
    """Alias del endpoint de búsqueda"""
    return await search_diagnosis(request)

# ==========================================
# ENDPOINTS DEL PROCESADOR DE QUERIES LLM
# ==========================================
@app.post("/api/analyze-query")
async def analyze_query(request: SearchRequest):
    """
    Analiza una consulta para extraer síntomas y hallazgos clave usando LLM
    
    Args:
        request: Objeto con la query
    
    Returns:
        Análisis de la consulta
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{LLM_QUERY_PROCESSOR_URL}/analyze",
                json={"query": request.query}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "LLM processor error")
                )
            
            return response.json()
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="LLM processor request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to LLM processor service"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gateway error: {str(e)}"
        )

@app.post("/api/correct-query")
async def correct_query(request: SearchRequest):
    """
    Corrige y normaliza una consulta
    
    Args:
        request: Objeto con la query
    
    Returns:
        Consulta corregida y normalizada
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{LLM_QUERY_PROCESSOR_URL}/correct",
                json={"query": request.query}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "LLM processor error")
                )
            
            return response.json()
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="LLM processor request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to LLM processor service"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gateway error: {str(e)}"
        )

@app.post("/api/process-query")
async def process_query(request: SearchRequest):
    """
    Pipeline completo: Análisis + Corrección
    
    Args:
        request: Objeto con la query
    
    Returns:
        Consulta procesada completamente con análisis
    """
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{LLM_QUERY_PROCESSOR_URL}/process",
                json={"query": request.query}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json().get("detail", "LLM processor error")
                )
            
            return response.json()
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="LLM processor request timeout"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to LLM processor service"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gateway error: {str(e)}"
        )


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3000,
        reload=True
    )
