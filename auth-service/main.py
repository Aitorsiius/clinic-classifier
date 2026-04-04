"""
Servicio de Autenticación - CIE-10 Classifier

Microservicio responsable de:
- Autenticación de usuarios (login)
- Generación y validación de tokens JWT
- Renovación de tokens
"""

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import jwt
from datetime import datetime, timedelta, timezone
import os
import uvicorn
from typing import Optional

# ==========================================
# CONFIGURACIÓN
# ==========================================
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
AUTH_SERVICE_PORT = int(os.getenv("AUTH_SERVICE_PORT", "8004"))

# Base de datos simulada de usuarios
USERS_DB = {
    "auditor@clinic.com": "auditor123"  # Por ahora sin hashear
}

# ==========================================
# MODELOS PYDANTIC
# ==========================================
class LoginRequest(BaseModel):
    """Solicitud de login"""
    email: str
    password: str

class LoginResponse(BaseModel):
    """Respuesta de login"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class VerifyTokenRequest(BaseModel):
    """Solicitud para verificar token"""
    token: str

class VerifyTokenResponse(BaseModel):
    """Respuesta de verificación de token"""
    valid: bool
    email: Optional[str] = None
    expires_at: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    """Solicitud para renovar token"""
    token: str

class RefreshTokenResponse(BaseModel):
    """Respuesta de renovación de token"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
def create_token(email: str, hours: Optional[int] = None) -> tuple[str, datetime]:
    """
    Crea un JWT token para el usuario
    
    Args:
        email: Email del usuario
        hours: Horas de expiración (usa la configuración global si no se especifica)
        
    Returns:
        Tupla de (token, datetime_expiracion)
    """
    if hours is None:
        hours = JWT_EXPIRATION_HOURS
        
    exp_time = datetime.now(timezone.utc) + timedelta(hours=hours)
    payload = {
        "email": email,
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
    Hashea una contraseña (usar bcrypt o similar en producción)
    
    Args:
        password: Contraseña en texto plano
        
    Returns:
        Contraseña hasheada
    """
    # TODO: Usar bcrypt o argon2 en producción
    return password

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra su hash
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Contraseña hasheada
        
    Returns:
        True si coinciden, False en otro caso
    """
    # TODO: Usar bcrypt o argon2 en producción
    return hash_password(plain_password) == hashed_password

# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="Auth Service - CIE-10 Classifier",
    description="Microservicio de autenticación para CIE-10 Classifier",
    version="1.0.0"
)

# Configurar CORS
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

@app.get("/health", tags=["Health"])
async def health_check():
    """Verificar que el servicio está funcionando"""
    return {
        "status": "healthy",
        "service": "auth-service",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """
    Endpoint de login
    
    Args:
        request: Credenciales de login (email y password)
        
    Returns:
        LoginResponse con token JWT
        
    Raises:
        HTTPException: Si las credenciales son inválidas
    """
    # Validar credenciales
    if request.email not in USERS_DB:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    stored_password = USERS_DB[request.email]
    if not verify_password(request.password, stored_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Crear token
    token, exp_time = create_token(request.email)
    expires_in = int((exp_time - datetime.now(timezone.utc)).total_seconds())
    
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in
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
        email = payload.get("email")
        exp = payload.get("exp")
        
        # Convertir timestamp Unix a datetime ISO
        exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
        exp_iso = exp_datetime.isoformat()
        
        return VerifyTokenResponse(
            valid=True,
            email=email,
            expires_at=exp_iso
        )
    except HTTPException:
        return VerifyTokenResponse(
            valid=False,
            email=None,
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
    email = payload.get("email")
    
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    # Crear nuevo token
    new_token, exp_time = create_token(email)
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
    return {
        "valid": True,
        "email": payload.get("email"),
        "expires_at": datetime.utcfromtimestamp(payload.get("exp")).isoformat()
    }

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AUTH_SERVICE_PORT,
        log_level="info"
    )
