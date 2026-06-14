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
import time
from typing import Annotated

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    algorithm: Optional[str] = "hybrid"
    # Activa el pipeline de búsqueda con IA: el backend pide a la primera fase
    # (LLM) un texto enriquecido y se lo pasa al bi-encoder + cross-encoder.
    use_ai: bool = False
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
    # Indica si la respuesta se generó con el pipeline de IA activado.
    used_ai: bool = False
    # Tiempo total (ms) del pipeline de búsqueda en el backend: incluye la fase
    # de IA (si está activa), la recuperación con el bi-encoder y el re-ranking
    # con el cross-encoder. Se devuelve al cliente y se persiste en el log.
    search_time_ms: Optional[float] = None
    # Bloque del asistente inteligente (solo presente en modo IA): diagnóstico en
    # lenguaje natural y consejos de mejora por información faltante. Es opcional
    # e independiente de la lista de resultados, que mantiene su estructura.
    assistant: Optional[dict] = None


# ==========================================
# CONFIGURACIÓN
# ==========================================
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://localhost:8006")
# Procesador de consultas LLM (primera fase del pipeline de búsqueda con IA).
# El backend orquesta el pipeline: cuando la búsqueda llega con use_ai=True,
# pide aquí el texto enriquecido y el bloque del asistente antes de recuperar.
LLM_QUERY_PROCESSOR_URL = os.getenv("LLM_QUERY_PROCESSOR_URL", "http://localhost:8003")
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
    ai_suggestions: Optional[dict] = None,
    search_time_ms: Optional[float] = None
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
                    "ai_suggestions": ai_suggestions,
                    "search_time_ms": search_time_ms
                },
                timeout=2.0
            )
    except Exception as e:
        logger.warning(f"No se pudo registrar búsqueda en log-service: {e}")

# ==========================================
# PIPELINE DE BÚSQUEDA CON IA (PRIMERA FASE)
# ==========================================
async def enrich_query_with_ai(query: str) -> Optional[dict]:
    """Primera fase del pipeline de búsqueda con IA.

    Pide al procesador LLM el bloque del asistente (diagnostico + consejos) y el
    texto enriquecido que después se usa para recuperar y re-rankear. Si el LLM
    no está disponible o falla, devuelve None y la búsqueda continúa en modo
    normal (degradación elegante, nunca rompe la clasificación).

    Returns:
        dict con las claves 'diagnostico', 'consejos_mejora', 'enriched_query',
        'is_valid_medical_query' o None si no se pudo enriquecer.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{LLM_QUERY_PROCESSOR_URL}/ai-search",
                json={"query": query},
            )
            if response.status_code != 200:
                logger.warning(
                    "El procesador LLM respondió con estado %s en /ai-search",
                    response.status_code,
                )
                return None
            return response.json()
    except Exception as e:
        logger.warning("No se pudo enriquecer la consulta con IA: %s", e)
        return None


def _build_hierarchy_items(payload_data) -> List[HierarchyItem]:
    """Construye la lista de HierarchyItem a partir del payload de un resultado."""
    hierarchy_data: List[HierarchyItem] = []
    if not isinstance(payload_data, dict):
        return hierarchy_data
    metadata = payload_data.get("metadata", {})
    hierarchy_raw = metadata.get("hierarchy", []) if isinstance(metadata, dict) else []
    for item in hierarchy_raw:
        if isinstance(item, dict):
            hierarchy_data.append(HierarchyItem(code=item.get("id", ""), title=item.get("title", "")))
        else:
            hierarchy_data.append(HierarchyItem(code=getattr(item, "id", ""), title=getattr(item, "title", "")))
    return hierarchy_data


def _to_search_result(result) -> SearchResult:
    """Normaliza un resultado del motor (dict u objeto) a un SearchResult."""
    if isinstance(result, dict):
        score = result.get("score", 0.0)
        payload_data = result.get("payload", {})
    else:
        score = getattr(result, "score", 0.0)
        payload_data = getattr(result, "payload", {})

    is_dict = isinstance(payload_data, dict)
    payload = Payload(
        id=payload_data.get("id", "") if is_dict else getattr(payload_data, "id", ""),
        title=payload_data.get("title", "") if is_dict else getattr(payload_data, "title", ""),
        metadata=Metadata(hierarchy=_build_hierarchy_items(payload_data)),
        search_text=payload_data.get("search_text") if is_dict else getattr(payload_data, "search_text", None),
    )
    return SearchResult(score=score, original_score=score, payload=payload)


def format_search_results(results) -> List[SearchResult]:
    """Transforma los resultados crudos del motor al formato de respuesta de la API."""
    return [_to_search_result(result) for result in results]

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


@app.post("/search", response_model=SearchResponse, responses={503: {"description": "Search engine not initialized"}, 
                                                               500: {"description": INTERNAL_ERROR_DETAIL}})
async def search_diagnosis(request: SearchRequest, req: Request, session_id: Annotated[str | None, Header()] = None, user_id: Annotated[str | None, Header()] = None):
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
        # Cronómetro del pipeline completo de búsqueda (IA + recuperación +
        # re-ranking). Se mide en el backend para que el valor sea fiable y se
        # devuelve al cliente y se persiste en el log, tanto en modo IA como sin
        # IA.
        start_time = time.perf_counter()

        # Obtener headers si no están en los parámetros
        if not session_id:
            session_id = req.headers.get("x-session-id")
        if not user_id:
            user_id = req.headers.get("x-user-id")
        
        # Obtener el top_k del request, con un máximo de 20
        requested_top_k = request.top_k if request.top_k and request.top_k > 0 else 5
        top_k = min(requested_top_k, 20)

        # --- PIPELINE DE BÚSQUEDA CON IA (PRIMERA FASE) ---
        # Cuando use_ai está activo, la IA enriquece la consulta antes de la
        # recuperación. El bloque del asistente (diagnóstico + consejos) viaja
        # aparte; los resultados conservan su estructura habitual.
        enriched_query: Optional[str] = None
        assistant_block: Optional[dict] = None
        # Valores efectivos para el registro/log (en modo IA reflejan lo generado
        # por esta fase; si el cliente ya los envió, se respetan como respaldo).
        effective_used_ai = request.used_ai_assistant
        effective_ai_suggestions = request.ai_suggestions

        if request.use_ai:
            ai_data = await enrich_query_with_ai(request.query)
            if ai_data:
                candidate = (ai_data.get("enriched_query") or "").strip()
                # Solo usamos el texto enriquecido si la consulta es clínicamente
                # interpretable y aporta contenido.
                if ai_data.get("is_valid_medical_query", True) and candidate:
                    enriched_query = candidate
                assistant_block = {
                    "diagnostico": ai_data.get("diagnostico", ""),
                    "consejos_mejora": ai_data.get("consejos_mejora", []),
                    "enriched_query": ai_data.get("enriched_query", ""),
                    "is_valid_medical_query": ai_data.get("is_valid_medical_query", True),
                    "processing_time_ms": ai_data.get("processing_time_ms"),
                }
                effective_used_ai = True
                effective_ai_suggestions = assistant_block

        # Realizar búsqueda (en modo IA con el texto enriquecido)
        results = search_engine.search(request.query, top_k=top_k, enriched_query=enriched_query)
        logger.info("Búsqueda completada: %d resultados (IA=%s)", len(results), request.use_ai)

        # Transformar resultados al formato esperado
        formatted_results = format_search_results(results)

        # Tiempo total del pipeline (ms), redondeado a 2 decimales.
        search_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Registrar búsqueda en log-service de forma asíncrona
        if session_id and user_id:
            try:
                ip_address = req.client.host if req.client else "unknown"
                # Convertir resultados a formato serializable
                results_for_log = [result.dict() for result in formatted_results]
                await register_search_log(
                        session_id=session_id,
                        user_id=user_id,
                        query=request.query,
                        top_k=top_k,
                        results_count=len(formatted_results),
                        results=results_for_log,
                        ip_address=ip_address,
                        status="success",
                        used_ai_assistant=effective_used_ai,
                        ai_suggestions=effective_ai_suggestions,
                        search_time_ms=search_time_ms
                    )
            except Exception as e:
                logger.warning(f"No se pudo registrar búsqueda en log-service: {e}")
        
        return SearchResponse(
            results=formatted_results,
            query=request.query,
            count=len(formatted_results),
            used_ai=request.use_ai,
            search_time_ms=search_time_ms,
            assistant=assistant_block
        )
    
    except Exception as e:
        # Registrar error en log-service
        if session_id and user_id:
            try:
                ip_address = req.client.host if req.client else "unknown"
                await register_search_log(
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
            except Exception as log_err:
                logger.warning(f"No se pudo registrar error en log-service: {log_err}")
        
        logger.exception("Error en búsqueda: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/export-csv", responses={500: {"description": INTERNAL_ERROR_DETAIL}})
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
