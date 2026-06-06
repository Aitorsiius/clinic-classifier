from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from datetime import datetime, timezone
from main import MedicalSearchEngine
import csv
import io
import os
import httpx
import logging
import asyncio

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    algorithm: Optional[str] = "hybrid"
    # Campos para el asistente de IA
    used_ai_assistant: bool = False
    ai_suggestions: Optional[dict] = None


class HierarchyItem(BaseModel):
    code: str
    title: str


class Metadata(BaseModel):
    hierarchy: List[HierarchyItem]


class Payload(BaseModel):
    id: str
    title: str
    metadata: Metadata
    search_text: Optional[str] = None


class SearchResult(BaseModel):
    score: float
    original_score: float
    payload: Payload


class SearchResponse(BaseModel):
    results: List[SearchResult]
    query: str
    count: int


# ==========================================
# CONFIGURACIÓN
# ==========================================
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://localhost:8006")
# En contenedores debe ser 0.0.0.0 para aceptar conexiones del resto de
# servicios de la red interna de Docker; el acceso queda acotado por la red
# bridge aislada y por los puertos publicados en docker-compose.
HOST = os.getenv("HOST", "0.0.0.0")
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================
async def register_search_log(
    session_id: str, 
    user_id: str, 
    query: str, 
    top_k: int, 
    results_count: int, 
    ip_address: str, 
    status: str, 
    error_message: Optional[str] = None, 
    results: Optional[list] = None,
    used_ai_assistant: bool = False,
    ai_suggestions: Optional[dict] = None
):
    """Registra una búsqueda en log-service de forma no-bloqueante"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{LOG_SERVICE_URL}/searches",
                json={
                    "session_id": session_id,
                    "user_id": user_id,
                    "query": query,
                    "top_k": top_k,
                    "results_count": results_count,
                    "results": results,  # Pasar todos los resultados
                    "ip_address": ip_address,
                    "status": status,
                    "error_message": error_message,
                    "used_ai_assistant": used_ai_assistant,
                    "ai_suggestions": ai_suggestions
                },
                timeout=2.0
            )
    except Exception as e:
        logger.warning(f"No se pudo registrar búsqueda en log-service: {e}")

# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================

app = FastAPI(
    title="CIE-10 Classifier API",
    description="API para clasificación de diagnósticos médicos usando CIE-10",
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

# Inicialización del motor de búsqueda
logger.info("Inicializando Motor de Búsqueda...")
try:
    search_engine = MedicalSearchEngine()
    logger.info("Motor de Búsqueda listo")
except Exception:
    logger.exception("Error al inicializar el motor de búsqueda")
    search_engine = None

# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/")
async def root():
    """Endpoint raíz para verificar que el servicio está activo"""
    return {
        "service": "CIE-10 Classifier Backend",
        "status": "running",
        "search_engine": "ready" if search_engine else "not_ready"
    }


@app.get("/health")
async def health_check():
    """Verificar que el servicio está funcionando"""
    return {
        "status": "healthy",
        "service": "backend-service",
        "timestamp": datetime.now().isoformat(),
        "search_engine": "ready" if search_engine else "not_ready"
    }


@app.post("/search", response_model=SearchResponse)
async def search_diagnosis(request: SearchRequest, req: Request, session_id: Optional[str] = Header(None), user_id: Optional[str] = Header(None)):
    """
    Endpoint principal para buscar diagnósticos
    
    Args:
        request: Objeto con la query y top_k opcional
        req: Request object
        session_id: Session ID from header
        user_id: User ID from header
    
    Returns:
        SearchResponse con los resultados encontrados
    """
    if not search_engine:
        raise HTTPException(status_code=503, detail="Search engine not initialized")
    
    try:
        # Obtener headers si no están en los parámetros
        if not session_id:
            session_id = req.headers.get("x-session-id")
        if not user_id:
            user_id = req.headers.get("x-user-id")
        
        # Obtener el top_k del request, con un máximo de 20
        requested_top_k = request.top_k if request.top_k and request.top_k > 0 else 5
        top_k = min(requested_top_k, 20)
        
        # Realizar búsqueda
        results = search_engine.search(request.query, top_k=top_k)
        logger.info("Búsqueda completada: %d resultados", len(results))
        
        # Transformar resultados al formato esperado
        formatted_results = []
        for result in results:
            # Extraer información del resultado
            if isinstance(result, dict):
                score = result.get("score", 0.0)
                original_score = result.get("score", 0.0)
                payload_data = result.get("payload", {})
            else:
                # Si no es dict, intentar acceder como objeto
                score = getattr(result, "score", 0.0)
                original_score = getattr(result, "score", 0.0)
                payload_data = getattr(result, "payload", {})
            
            # Extraer jerarquía del payload si existe
            hierarchy_data = []
            if isinstance(payload_data, dict):
                metadata = payload_data.get("metadata", {})
                hierarchy_raw = metadata.get("hierarchy", []) if isinstance(metadata, dict) else []
                
                # Convertir jerarquía a objetos HierarchyItem
                for item in hierarchy_raw:
                    if isinstance(item, dict):
                        hierarchy_data.append(HierarchyItem(
                            code=item.get("id", ""),
                            title=item.get("title", "")
                        ))
                    else:
                        # Si es un objeto, intenta acceder a sus atributos
                        hierarchy_data.append(HierarchyItem(
                            code=getattr(item, "id", ""),
                            title=getattr(item, "title", "")
                        ))
            
            # Crear objeto Payload
            payload = Payload(
                id=payload_data.get("id", "") if isinstance(payload_data, dict) else getattr(payload_data, "id", ""),
                title=payload_data.get("title", "") if isinstance(payload_data, dict) else getattr(payload_data, "title", ""),
                metadata=Metadata(hierarchy=hierarchy_data),
                search_text=payload_data.get("search_text") if isinstance(payload_data, dict) else getattr(payload_data, "search_text", None)
            )
            
            # Crear objeto SearchResult
            search_result = SearchResult(
                score=score,
                original_score=original_score,
                payload=payload
            )
            formatted_results.append(search_result)
        
        # Registrar búsqueda en log-service de forma asíncrona
        if session_id and user_id:
            try:
                ip_address = req.client.host if req.client else "unknown"
                # Convertir resultados a formato serializable
                results_for_log = [result.dict() for result in formatted_results]
                asyncio.create_task(
                    register_search_log(
                        session_id=session_id,
                        user_id=user_id,
                        query=request.query,
                        top_k=top_k,
                        results_count=len(formatted_results),
                        results=results_for_log,
                        ip_address=ip_address,
                        status="success",
                        used_ai_assistant=request.used_ai_assistant,
                        ai_suggestions=request.ai_suggestions
                    )
                )
            except Exception as e:
                logger.warning(f"No se pudo registrar búsqueda en log-service: {e}")
        
        return SearchResponse(
            results=formatted_results,
            query=request.query,
            count=len(formatted_results)
        )
    
    except Exception as e:
        # Registrar error en log-service
        if session_id and user_id:
            try:
                ip_address = req.client.host if req.client else "unknown"
                asyncio.create_task(
                    register_search_log(
                        session_id=session_id,
                        user_id=user_id,
                        query=request.query,
                        top_k=top_k if 'top_k' in locals() else 5,
                        results_count=0,
                        ip_address=ip_address,
                        status="error",
                        error_message=str(e),
                        used_ai_assistant=request.used_ai_assistant,
                        ai_suggestions=request.ai_suggestions
                    )
                )
            except Exception as log_err:
                logger.warning(f"No se pudo registrar error en log-service: {log_err}")
        
        logger.exception("Error en búsqueda: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/export-csv")
async def export_results(records: List[dict]):
    """Exportar resultados a CSV"""
    try:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=records[0].keys() if records else [])
        writer.writeheader()
        writer.writerows(records)
        
        return {
            "status": "success",
            "csv": output.getvalue()
        }
    except Exception as e:
        logger.exception("Error exportando resultados a CSV: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(
        app,
        host=HOST,
        port=port,
        log_level="info"
    )
