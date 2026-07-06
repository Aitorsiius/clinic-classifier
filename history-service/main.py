"""
Servicio de Historial - CIE-10 Classifier

Microservicio responsable de:
- Gestionar el historial de búsquedas de los usuarios
- Proporcionar búsquedas segmentadas temporalmente
- Permitir consultas y filtros sobre el historial
"""

import re

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import uvicorn
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import logging
import jwt
from typing import Annotated

# ==========================================
# CONFIGURACIÓN
# ==========================================
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


HISTORY_SERVICE_PORT = int(os.getenv("HISTORY_SERVICE_PORT", "8007"))
# En contenedores debe ser 0.0.0.0 para aceptar conexiones del resto de
# servicios de la red interna de Docker; el acceso queda acotado por la red
# bridge aislada y por los puertos publicados en docker-compose.
HOST = os.getenv("HOST", "0.0.0.0")
MONGO_CONNECTION = os.getenv("MONGO_CONNECTION", "mongodb://localhost:27017/clinic-classifier")
JWT_SECRET = _require_env("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
# Orígenes permitidos para CORS (configurables por entorno). Por defecto solo
# el frontend local; nunca "*" junto con cookies/credenciales.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "https://localhost,https://localhost:3000"
    ).split(",")
    if origin.strip()
]
# Mensaje genérico para respuestas 5xx: evita filtrar detalles internos.
INTERNAL_ERROR_DETAIL = "Error interno del servidor"
MONGODB_CONNECTION_ERROR_DETAIL = "Error de conexión con MongoDB"

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# CONEXIÓN A MONGODB
# ==========================================
mongo_client = None
db = None
searches_collection = None

def init_mongodb():
    """Inicializa la conexión a MongoDB"""
    global mongo_client, db, searches_collection
    try:
        mongo_client = MongoClient(MONGO_CONNECTION, serverSelectionTimeoutMS=5000)
        # Verificar la conexión
        mongo_client.admin.command('ping')
        db = mongo_client.get_database('clinic-classifier')
        searches_collection = db['searches']
        
        # Crear índices para búsquedas
        searches_collection.create_index("user_id")
        searches_collection.create_index([("timestamp", -1)])
        searches_collection.create_index([("timestamp", -1), ("user_id", 1)])
        
        logger.info("✓ Conexión a MongoDB establecida correctamente en History Service")
        return True
    except ServerSelectionTimeoutError:
        logger.error("✗ Error: No se pudo conectar a MongoDB.")
        return False
    except Exception as e:
        logger.exception(f"✗ Error al conectar a MongoDB: {e}")
        return False

# Intentar conexión inicial
init_mongodb()

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class SearchHistoryItem(BaseModel):
    """Item individual del historial de búsqueda"""
    search_id: str
    query: str
    timestamp: str
    results_count: int
    results: Optional[list] = None
    used_ai_assistant: bool = False
    ai_suggestions: Optional[dict] = None
    # Tiempo total (ms) de la búsqueda (con o sin IA), para restaurarlo al
    # reabrir una búsqueda del historial.
    search_time_ms: Optional[float] = None
    status: str
    top_k: Optional[int] = None
    session_id: str

class SearchHistoryResponse(BaseModel):
    """Respuesta de historial segmentado"""
    user_id: str
    total: int
    history: dict
    generated_at: str

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

def verify_token(token: str) -> dict:
    """Verifica y decodifica un JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

def get_user_from_token(authorization: str = Header(None)) -> str:
    """Extrae el username del token JWT"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Falta la cabecera de autorización")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Esquema de autenticación inválido")
        
        payload = verify_token(token)
        username = payload.get("username")
        if not username:
            raise HTTPException(status_code=401, detail="Contenido del token inválido")
        return username
    except ValueError:
        raise HTTPException(status_code=401, detail="Cabecera de autorización inválida")
    
def sanitize_log(data: str) -> str:
    """
    Sanitiza strings reemplazando saltos de línea y retornos de carro 
    por espacios para evitar vulnerabilidades de Log Injection (CRLF).
    """
    if data is None:
        return ""
    # Convertimos a string por si llega un int u otro tipo
    return re.sub(r'[\r\n]', ' ', str(data))

# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="History Service - CIE-10 Classifier",
    description="Servicio de historial de búsquedas de usuarios",
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

@app.get("/health")
def health_check():
    """Health check del servicio"""
    if searches_collection is None:
        return {"status": "error", "message": MONGODB_CONNECTION_ERROR_DETAIL}
    return {"status": "ok", "service": "history-service"}

@app.get("/history", responses={500: {"description": MONGODB_CONNECTION_ERROR_DETAIL}})
async def get_search_history(
    username: Annotated[str, Depends(get_user_from_token)],
    limit: int = 100
):
    """
    Obtiene el historial de búsquedas del usuario autenticado,
    segmentado temporalmente: última hora, último día, última semana, último mes, último año.
    
    Args:
        username: Username extraído del token JWT
        limit: Límite de búsquedas a retornar (default: 100)
    
    Returns:
        Historial segmentado de búsquedas
    """
    try:
        if searches_collection is None:
            raise HTTPException(status_code=500, detail=MONGODB_CONNECTION_ERROR_DETAIL)
        
        # Primero, obtener el user_id (ObjectId) del usuario desde la colección users
        users_collection = db['users']
        user_doc = users_collection.find_one({"username": username})
        
        if not user_doc:
            logger.warning(f"Usuario no encontrado: {sanitize_log(username)}")
            return SearchHistoryResponse(
                user_id=username,
                total=0,
                history={"last_hour": [], "last_day": [], "last_week": [], "last_month": [], "last_year": [], "older": []},
                generated_at=datetime.now(timezone.utc).isoformat()
            )
        
        user_id = str(user_doc["_id"])
        
        now = datetime.now(timezone.utc)
        
        # Definir rangos temporales
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(weeks=1)
        one_month_ago = now - timedelta(days=30)
        one_year_ago = now - timedelta(days=365)
        
        # Obtener todas las búsquedas del usuario ordenadas por timestamp descendente
        # Buscar por user_id (ObjectId) que es como se guardan las búsquedas
        searches_docs = list(
            searches_collection.find({"user_id": user_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        
        # Segmentar búsquedas por tiempo
        history = {
            "last_hour": [],
            "last_day": [],
            "last_week": [],
            "last_month": [],
            "last_year": [],
            "older": []
        }
        
        for search_doc in searches_docs:
            timestamp = search_doc["timestamp"]
            
            # Asegurar que el timestamp tiene timezone
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            
            # Preparar objeto de búsqueda
            search_obj = {
                "search_id": search_doc.get("search_id", str(search_doc["_id"])),
                "query": search_doc["query"],
                "timestamp": timestamp.isoformat(),
                "results_count": search_doc.get("results_count", 0),
                "results": search_doc.get("results", []),
                "used_ai_assistant": search_doc.get("used_ai_assistant", False),
                "ai_suggestions": search_doc.get("ai_suggestions"),
                "search_time_ms": search_doc.get("search_time_ms"),
                "status": search_doc.get("status", "success"),
                "top_k": search_doc.get("top_k"),
                "session_id": search_doc.get("session_id")
            }
            
            # Segmentar según antigüedad
            if timestamp >= one_hour_ago:
                history["last_hour"].append(search_obj)
            elif timestamp >= one_day_ago:
                history["last_day"].append(search_obj)
            elif timestamp >= one_week_ago:
                history["last_week"].append(search_obj)
            elif timestamp >= one_month_ago:
                history["last_month"].append(search_obj)
            elif timestamp >= one_year_ago:
                history["last_year"].append(search_obj)
            else:
                history["older"].append(search_obj)
        
        total_count = len(searches_docs)
        
        logger.info(f"Historial obtenido para usuario {sanitize_log(username)}: {total_count} búsquedas")
        
        return {
            "user_id": username,  # Retornar username para consistencia
            "total": total_count,
            "history": history,
            "generated_at": now.isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener historial de búsquedas: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.get("/history/count", responses={500: {"description": MONGODB_CONNECTION_ERROR_DETAIL}})
async def get_history_count(
    username: Annotated[str, Depends(get_user_from_token)]
):
    """
    Obtiene el número total de búsquedas en el historial del usuario
    
    Args:
        username: Username extraído del token JWT
    
    Returns:
        Conteo total de búsquedas
    """
    try:
        if searches_collection is None:
            raise HTTPException(status_code=500, detail=MONGODB_CONNECTION_ERROR_DETAIL)
        
        # Obtener el user_id (ObjectId) del usuario
        users_collection = db['users']
        user_doc = users_collection.find_one({"username": username})
        
        if not user_doc:
            return {
                "user_id": username,
                "total_searches": 0
            }
        
        user_id = str(user_doc["_id"])
        count = searches_collection.count_documents({"user_id": user_id})
        
        return {
            "user_id": username,
            "total_searches": count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al contar búsquedas: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.get("/history/recent", responses={500: {"description": MONGODB_CONNECTION_ERROR_DETAIL}})
async def get_recent_searches(
    username: Annotated[str, Depends(get_user_from_token)],
    limit: int = 10
):
    """
    Obtiene las búsquedas más recientes del usuario (sin segmentación temporal)
    
    Args:
        username: Username extraído del token JWT
        limit: Número de búsquedas a retornar (default: 10)
    
    Returns:
        Lista de búsquedas recientes
    """
    try:
        if searches_collection is None:
            raise HTTPException(status_code=500, detail=MONGODB_CONNECTION_ERROR_DETAIL)
        
        # Obtener el user_id (ObjectId) del usuario
        users_collection = db['users']
        user_doc = users_collection.find_one({"username": username})
        
        if not user_doc:
            return {
                "user_id": username,
                "count": 0,
                "searches": []
            }
        
        user_id = str(user_doc["_id"])
        
        # Obtener búsquedas más recientes
        searches_docs = list(
            searches_collection.find({"user_id": user_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        
        recent_searches = []
        for search_doc in searches_docs:
            timestamp = search_doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            
            recent_searches.append({
                "search_id": search_doc.get("search_id", str(search_doc["_id"])),
                "query": search_doc["query"],
                "timestamp": timestamp.isoformat(),
                "results_count": search_doc.get("results_count", 0),
                "used_ai_assistant": search_doc.get("used_ai_assistant", False),
                "status": search_doc.get("status", "success")
            })
        
        return {
            "user_id": username,
            "count": len(recent_searches),
            "searches": recent_searches
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener búsquedas recientes: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=HISTORY_SERVICE_PORT,
        log_level="info"
    )
