"""
Servicio de Logs - CIE-10 Classifier

Microservicio responsable de:
- Gestionar sesiones de usuario (login/logout)
- Registrar búsquedas realizadas
- Registrar auditorías completadas
- Proporcionar acceso a los logs para el panel de administración
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import uvicorn
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from enum import Enum
from bson import ObjectId
import logging

# ==========================================
# CONFIGURACIÓN
# ==========================================
LOG_SERVICE_PORT = int(os.getenv("LOG_SERVICE_PORT", "8006"))
# En contenedores debe ser 0.0.0.0 para aceptar conexiones del resto de
# servicios de la red interna de Docker; el acceso queda acotado por la red
# bridge aislada y por los puertos publicados en docker-compose.
HOST = os.getenv("HOST", "0.0.0.0")
MONGO_CONNECTION = os.getenv("MONGO_CONNECTION", "mongodb://localhost:27017/clinic-classifier")
# Orígenes permitidos para CORS (configurables por entorno). Por defecto solo
# el frontend local; nunca "*" junto con cookies/credenciales.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost,http://localhost:3000"
    ).split(",")
    if origin.strip()
]
# Mensaje genérico para respuestas 5xx: evita filtrar detalles internos.
INTERNAL_ERROR_DETAIL = "Internal server error"

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
sessions_collection = None
searches_collection = None
audits_collection = None
admin_actions_collection = None

def init_mongodb():
    """Inicializa la conexión a MongoDB"""
    global mongo_client, db, sessions_collection, searches_collection, audits_collection, admin_actions_collection
    try:
        mongo_client = MongoClient(MONGO_CONNECTION, serverSelectionTimeoutMS=5000)
        # Verificar la conexión
        mongo_client.admin.command('ping')
        db = mongo_client.get_database('clinic-classifier')
        sessions_collection = db['sessions']
        searches_collection = db['searches']
        audits_collection = db['audits']
        admin_actions_collection = db['admin_actions']
        
        # Crear índices para sesiones
        sessions_collection.create_index("user_id")
        sessions_collection.create_index("session_id", unique=True)
        sessions_collection.create_index([("created_at", -1)])
        sessions_collection.create_index([("closed_at", 1)])
        
        # Crear índices para búsquedas
        searches_collection.create_index("session_id")
        searches_collection.create_index("user_id")
        searches_collection.create_index([("timestamp", -1)])
        searches_collection.create_index([("timestamp", -1), ("user_id", 1)])
        
        # Crear índices para auditorías
        audits_collection.create_index("session_id")
        audits_collection.create_index("user_id")
        audits_collection.create_index([("timestamp", -1)])
        audits_collection.create_index([("timestamp", -1), ("user_id", 1)])
        
        # Crear índices para acciones de administración (gestión de usuarios)
        admin_actions_collection.create_index("session_id")
        admin_actions_collection.create_index("actor_user_id")
        admin_actions_collection.create_index("target_user_id")
        admin_actions_collection.create_index("action")
        admin_actions_collection.create_index([("timestamp", -1)])
        admin_actions_collection.create_index([("timestamp", -1), ("actor_user_id", 1)])
        
        logger.info("✓ Conexión a MongoDB establecida correctamente")
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

class SessionCreateRequest(BaseModel):
    """Solicitud para crear una nueva sesión"""
    user_id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class SessionCreateResponse(BaseModel):
    """Respuesta de creación de sesión"""
    session_id: str
    user_id: str
    created_at: str

class SessionCloseRequest(BaseModel):
    """Solicitud para cerrar una sesión"""
    session_id: str

class SessionCloseResponse(BaseModel):
    """Respuesta de cierre de sesión"""
    session_id: str
    closed_at: str
    duration_seconds: int

class SearchRecord(BaseModel):
    """Registro de búsqueda"""
    session_id: str
    user_id: str
    query: str
    top_k: Optional[int] = None
    results_count: int = 0
    results: Optional[list] = None  # Guardar resultados completos en JSON
    ip_address: Optional[str] = None
    description: Optional[str] = None
    status: str = "success"
    error_message: Optional[str] = None
    details: Optional[dict] = None
    # Campos del asistente de IA
    used_ai_assistant: bool = False  # Si se usó el asistente de IA
    ai_suggestions: Optional[dict] = None  # Sugerencias del asistente de IA (original_query, corrected_query, primary_symptoms, secondary_symptoms, search_keywords, processing_time_ms)

class SearchResponse(BaseModel):
    """Respuesta de búsqueda registrada"""
    search_id: str
    session_id: str
    user_id: str
    timestamp: str
    status: str

class AuditRecord(BaseModel):
    """Registro de auditoría - Información exportable completa"""
    session_id: str
    user_id: str
    records_count: int
    algorithm: Optional[str] = None
    top_k: Optional[int] = None
    ip_address: Optional[str] = None
    description: Optional[str] = None
    status: str = "success"
    error_message: Optional[str] = None
    details: Optional[dict] = None

class AuditResponse(BaseModel):
    """Respuesta de auditoría registrada"""
    audit_id: str
    session_id: str
    user_id: str
    timestamp: str
    status: str

class Session(BaseModel):
    """Modelo de sesión"""
    session_id: str
    user_id: str
    created_at: str
    closed_at: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    duration_seconds: Optional[int] = None

class SessionListResponse(BaseModel):
    """Respuesta de lista de sesiones"""
    total: int
    sessions: List[Session]

class SearchListResponse(BaseModel):
    """Respuesta de lista de búsquedas"""
    total: int
    searches: List[dict]

class AIAnalysisUpdate(BaseModel):
    """Modelo para actualizar análisis de IA en una búsqueda"""
    session_id: str
    query: str  # Para identificar la búsqueda más reciente
    ai_analysis: dict  # Análisis completo del IA incluyendo todos los campos

class AuditListResponse(BaseModel):
    """Respuesta de lista de auditorías"""
    total: int
    audits: List[dict]

class AdminActionRecord(BaseModel):
    """
    Registro de una acción de administración sobre usuarios.

    Permite una trazabilidad total de la gestión de usuarios: quién realizó la
    acción (actor), sobre quién recayó (target), en qué sesión y con qué detalles.
    """
    action: str  # create_user | update_role | change_password | delete_user
    actor_user_id: str  # user_id del administrador que realiza la acción
    actor_username: Optional[str] = None
    target_user_id: Optional[str] = None  # user_id del usuario afectado
    target_username: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = "success"
    error_message: Optional[str] = None
    details: Optional[dict] = None  # p. ej. roles antiguos/nuevos

class AdminActionResponse(BaseModel):
    """Respuesta de registro de acción de administración"""
    action_id: str
    action: str
    actor_user_id: str
    target_user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str
    status: str

class AdminActionListResponse(BaseModel):
    """Respuesta de lista de acciones de administración"""
    total: int
    actions: List[dict]

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

def serialize_doc(doc) -> dict:
    """Convierte un documento de MongoDB a un diccionario serializable"""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return doc

def get_session_by_id(session_id: str) -> Optional[dict]:
    """Obtiene una sesión por su ID"""
    try:
        if sessions_collection is None:
            init_mongodb()
        
        if sessions_collection is None:
            return None
        
        session = sessions_collection.find_one({"session_id": session_id})
        return session
    except Exception as e:
        logger.exception(f"Error al obtener sesión: {e}")
        return None

def get_session_by_user_id_active(user_id: str) -> Optional[dict]:
    """Obtiene la sesión activa de un usuario"""
    try:
        if sessions_collection is None:
            init_mongodb()
        
        if sessions_collection is None:
            return None
        
        session = sessions_collection.find_one({"user_id": user_id, "closed_at": None})
        return session
    except Exception as e:
        logger.exception(f"Error al obtener sesión activa: {e}")
        return None

# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================
app = FastAPI(
    title="Log Service - CIE-10 Classifier",
    description="Servicio de logs para registro de actividades de usuarios",
    version="2.0.0"
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
    if sessions_collection is None or searches_collection is None or audits_collection is None:
        return {"status": "error", "message": "MongoDB not connected"}
    return {"status": "ok", "service": "log-service"}

@app.post("/sessions/create", response_model=SessionCreateResponse)
async def create_session(request: SessionCreateRequest):
    """
    Crea una nueva sesión para un usuario.
    Se llama cuando un usuario hace login.
    """
    try:
        if sessions_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        # Generar ID único para la sesión
        session_id = str(ObjectId())
        now = datetime.now(timezone.utc)
        
        session_doc = {
            "session_id": session_id,
            "user_id": request.user_id,
            "created_at": now,
            "closed_at": None,
            "ip_address": request.ip_address,
            "user_agent": request.user_agent
        }
        
        result = sessions_collection.insert_one(session_doc)
        
        if result.inserted_id:
            logger.info(f"Sesión creada: {session_id} para usuario {request.user_id}")
            return SessionCreateResponse(
                session_id=session_id,
                user_id=request.user_id,
                created_at=now.isoformat()
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to create session")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al crear sesión: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/sessions/close", response_model=SessionCloseResponse)
async def close_session(request: SessionCloseRequest):
    """
    Cierra una sesión existente.
    Se llama cuando un usuario hace logout.
    Actualiza el campo closed_at con la hora actual.
    """
    try:
        if sessions_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        session = get_session_by_id(request.session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if session.get("closed_at") is not None:
            raise HTTPException(status_code=400, detail="Session already closed")
        
        now = datetime.now(timezone.utc)
        created_at = session["created_at"]
        
        # Asegurar que ambos datetimes tienen timezone
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        # Calcular duración en segundos
        duration_seconds = int((now - created_at).total_seconds())
        
        # Actualizar la sesión con closed_at
        update_result = sessions_collection.update_one(
            {"session_id": request.session_id},
            {
                "$set": {
                    "closed_at": now,
                    "duration_seconds": duration_seconds
                }
            }
        )
        
        if update_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        
        logger.info(f"Sesión cerrada: {request.session_id} - Duración: {duration_seconds}s")
        
        return SessionCloseResponse(
            session_id=request.session_id,
            closed_at=now.isoformat(),
            duration_seconds=duration_seconds
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al cerrar sesión: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/searches", response_model=SearchResponse)
async def register_search(search: SearchRecord):
    """
    Registra una búsqueda realizada por un usuario.
    """
    try:
        if searches_collection is None:
            logger.error("MongoDB connection error when logging search")
            return SearchResponse(
                search_id="error",
                session_id=search.session_id,
                user_id=search.user_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="error"
            )
        
        # Verificar que la sesión existe
        session = get_session_by_id(search.session_id)
        if not session:
            logger.warning(f"Sesión no encontrada para búsqueda: {search.session_id}")
        
        search_id = str(ObjectId())
        now = datetime.now(timezone.utc)
        
        search_doc = {
            "search_id": search_id,
            "session_id": search.session_id,
            "user_id": search.user_id,
            "query": search.query,
            "top_k": search.top_k,
            "results_count": search.results_count,
            "results": search.results,  # Guardar todos los resultados en JSON
            "timestamp": now,
            "ip_address": search.ip_address,
            "description": search.description,
            "status": search.status,
            "error_message": search.error_message,
            "details": search.details,
            "used_ai_assistant": search.used_ai_assistant,
            "ai_suggestions": search.ai_suggestions
        }
        
        result = searches_collection.insert_one(search_doc)
        
        if result.inserted_id:
            logger.info(f"Búsqueda registrada: {search_id} - Query: {search.query}")
            return SearchResponse(
                search_id=search_id,
                session_id=search.session_id,
                user_id=search.user_id,
                timestamp=now.isoformat(),
                status="success"
            )
        else:
            logger.error("Failed to insert search record")
            return SearchResponse(
                search_id="error",
                session_id=search.session_id,
                user_id=search.user_id,
                timestamp=now.isoformat(),
                status="error"
            )
    
    except Exception as e:
        logger.exception(f"Error al registrar búsqueda: {e}")
        return SearchResponse(
            search_id="error",
            session_id=search.session_id,
            user_id=search.user_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="error"
        )

@app.patch("/searches/update-ai")
async def update_search_ai_analysis(update: AIAnalysisUpdate):
    """
    Actualiza los datos de análisis de IA para una búsqueda existente.
    Se llama desde el frontend después de obtener el análisis de IA.
    
    Args:
        update: Contiene session_id, query y ai_analysis (objeto completo del IA)
    
    Returns:
        Confirma la actualización
    """
    try:
        if searches_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        # Buscar la búsqueda más reciente con esta session_id y query
        search_doc = searches_collection.find_one({
            "session_id": update.session_id,
            "query": update.query
        }, sort=[("timestamp", -1)])
        
        if not search_doc:
            raise HTTPException(status_code=404, detail="Search record not found")
        
        # Extraer campos del ai_analysis
        ai_analysis_data = update.ai_analysis
        
        # Actualizar la búsqueda con todos los campos del análisis de IA
        update_result = searches_collection.update_one(
            {"_id": search_doc["_id"]},
            {
                "$set": {
                    "used_ai_assistant": True,
                    "ai_suggestions": {
                        "original_query": ai_analysis_data.get("original_query"),
                        "corrected_query": ai_analysis_data.get("corrected_query"),
                        "processing_time_ms": ai_analysis_data.get("processing_time_ms"),
                        "primary_symptoms": ai_analysis_data.get("analysis", {}).get("primary_symptoms", []),
                        "secondary_symptoms": ai_analysis_data.get("analysis", {}).get("secondary_symptoms", []),
                        "search_keywords": ai_analysis_data.get("analysis", {}).get("search_keywords", [])
                    }
                }
            }
        )
        
        if update_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Search record not found for update")
        
        logger.info(f"Análisis de IA actualizado para búsqueda: {update.query}")
        
        return {
            "status": "success",
            "message": "AI analysis updated successfully",
            "matched": update_result.matched_count,
            "modified": update_result.modified_count
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al actualizar análisis de IA: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/audits", response_model=AuditResponse)
async def register_audit(audit: AuditRecord):
    """
    Registra una auditoría realizada por un usuario.
    Contiene toda la información exportable del proceso de auditoría.
    """
    try:
        if audits_collection is None:
            logger.error("MongoDB connection error when logging audit")
            return AuditResponse(
                audit_id="error",
                session_id=audit.session_id,
                user_id=audit.user_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="error"
            )
        
        # Verificar que la sesión existe
        session = get_session_by_id(audit.session_id)
        if not session:
            logger.warning(f"Sesión no encontrada para auditoría: {audit.session_id}")
        
        audit_id = str(ObjectId())
        now = datetime.now(timezone.utc)
        
        audit_doc = {
            "audit_id": audit_id,
            "session_id": audit.session_id,
            "user_id": audit.user_id,
            "records_count": audit.records_count,
            "algorithm": audit.algorithm,
            "top_k": audit.top_k,
            "timestamp": now,
            "ip_address": audit.ip_address,
            "description": audit.description,
            "status": audit.status,
            "error_message": audit.error_message,
            "details": audit.details
        }
        
        result = audits_collection.insert_one(audit_doc)
        
        if result.inserted_id:
            logger.info(f"Auditoría registrada: {audit_id} - Registros: {audit.records_count}")
            return AuditResponse(
                audit_id=audit_id,
                session_id=audit.session_id,
                user_id=audit.user_id,
                timestamp=now.isoformat(),
                status="success"
            )
        else:
            logger.error("Failed to insert audit record")
            return AuditResponse(
                audit_id="error",
                session_id=audit.session_id,
                username=audit.username,
                timestamp=now.isoformat(),
                status="error"
            )
    
    except Exception as e:
        logger.exception(f"Error al registrar auditoría: {e}")
        return AuditResponse(
            audit_id="error",
            session_id=audit.session_id,
            user_id=audit.user_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="error"
        )

@app.get("/sessions", response_model=SessionListResponse)
async def get_sessions(
    username: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Obtiene una lista de sesiones (para el panel de administración).
    """
    try:
        if sessions_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        query = {}
        if username:
            query["username"] = username
        
        total = sessions_collection.count_documents(query)
        
        sessions_docs = list(
            sessions_collection.find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        
        sessions = []
        for session_doc in sessions_docs:
            duration_seconds = None
            if session_doc.get("closed_at"):
                duration_seconds = session_doc.get("duration_seconds")
            
            sessions.append(Session(
                session_id=session_doc["session_id"],
                user_id=session_doc["user_id"],
                created_at=session_doc["created_at"].isoformat(),
                closed_at=session_doc["closed_at"].isoformat() if session_doc.get("closed_at") else None,
                ip_address=session_doc.get("ip_address"),
                user_agent=session_doc.get("user_agent"),
                duration_seconds=duration_seconds
            ))
        
        return SessionListResponse(total=total, sessions=sessions)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener sesiones: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.get("/searches", response_model=SearchListResponse)
async def get_searches(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Obtiene una lista de búsquedas (para el panel de administración).
    """
    try:
        if searches_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        query = {}
        if session_id:
            query["session_id"] = session_id
        if user_id:
            query["user_id"] = user_id
        
        total = searches_collection.count_documents(query)
        
        searches_docs = list(
            searches_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        
        searches = []
        for search_doc in searches_docs:
            search_dict = dict(search_doc)
            search_dict["_id"] = str(search_dict["_id"])
            search_dict["timestamp"] = search_doc["timestamp"].isoformat()
            searches.append(search_dict)
        
        return SearchListResponse(total=total, searches=searches)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener búsquedas: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.get("/audits", response_model=AuditListResponse)
async def get_audits(
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Obtiene una lista de auditorías (para el panel de administración).
    """
    try:
        if audits_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")
        
        query = {}
        if session_id:
            query["session_id"] = session_id
        if user_id:
            query["user_id"] = user_id
        
        total = audits_collection.count_documents(query)
        
        audits_docs = list(
            audits_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        
        audits = []
        for audit_doc in audits_docs:
            audit_dict = dict(audit_doc)
            audit_dict["_id"] = str(audit_dict["_id"])
            audit_dict["timestamp"] = audit_doc["timestamp"].isoformat()
            audits.append(audit_dict)
        
        return AuditListResponse(total=total, audits=audits)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener auditorías: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/admin-actions", response_model=AdminActionResponse)
async def register_admin_action(action: AdminActionRecord):
    """
    Registra una acción de administración sobre usuarios (alta, cambio de rol,
    cambio de contraseña o baja), para tener una trazabilidad total.

    Incluye el actor (administrador), el usuario afectado, la sesión y los
    detalles relevantes de la operación.
    """
    try:
        if admin_actions_collection is None:
            logger.error("MongoDB connection error when logging admin action")
            return AdminActionResponse(
                action_id="error",
                action=action.action,
                actor_user_id=action.actor_user_id,
                target_user_id=action.target_user_id,
                session_id=action.session_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                status="error"
            )

        action_id = str(ObjectId())
        now = datetime.now(timezone.utc)

        action_doc = {
            "action_id": action_id,
            "action": action.action,
            "actor_user_id": action.actor_user_id,
            "actor_username": action.actor_username,
            "target_user_id": action.target_user_id,
            "target_username": action.target_username,
            "session_id": action.session_id,
            "ip_address": action.ip_address,
            "timestamp": now,
            "status": action.status,
            "error_message": action.error_message,
            "details": action.details
        }

        result = admin_actions_collection.insert_one(action_doc)

        if result.inserted_id:
            logger.info(
                f"Acción de admin registrada: {action.action} | actor={action.actor_username} "
                f"| target={action.target_username} | session={action.session_id}"
            )
            return AdminActionResponse(
                action_id=action_id,
                action=action.action,
                actor_user_id=action.actor_user_id,
                target_user_id=action.target_user_id,
                session_id=action.session_id,
                timestamp=now.isoformat(),
                status="success"
            )

        logger.error("Failed to insert admin action record")
        return AdminActionResponse(
            action_id="error",
            action=action.action,
            actor_user_id=action.actor_user_id,
            target_user_id=action.target_user_id,
            session_id=action.session_id,
            timestamp=now.isoformat(),
            status="error"
        )

    except Exception as e:
        logger.exception(f"Error al registrar acción de administración: {e}")
        return AdminActionResponse(
            action_id="error",
            action=action.action,
            actor_user_id=action.actor_user_id,
            target_user_id=action.target_user_id,
            session_id=action.session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="error"
        )

@app.get("/admin-actions", response_model=AdminActionListResponse)
async def get_admin_actions(
    session_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
    skip: int = 0
):
    """
    Obtiene la lista de acciones de administración sobre usuarios
    (para el panel de administración / auditoría de trazabilidad).
    """
    try:
        if admin_actions_collection is None:
            raise HTTPException(status_code=500, detail="MongoDB connection error")

        query = {}
        if session_id:
            query["session_id"] = session_id
        if actor_user_id:
            query["actor_user_id"] = actor_user_id
        if target_user_id:
            query["target_user_id"] = target_user_id
        if action:
            query["action"] = action

        total = admin_actions_collection.count_documents(query)

        actions_docs = list(
            admin_actions_collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )

        actions = []
        for action_doc in actions_docs:
            action_dict = dict(action_doc)
            action_dict["_id"] = str(action_dict["_id"])
            if action_doc.get("timestamp"):
                action_dict["timestamp"] = action_doc["timestamp"].isoformat()
            actions.append(action_dict)

        return AdminActionListResponse(total=total, actions=actions)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error al obtener acciones de administración: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=LOG_SERVICE_PORT,
        log_level="info"
    )
