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
from fastapi import BackgroundTasks

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
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
        "ALLOWED_ORIGINS", "https://localhost,https://localhost:3000"
    ).split(",")
    if origin.strip()
]
# Mensaje genérico para respuestas 5xx: evita filtrar detalles internos.
INTERNAL_ERROR_DETAIL = "Error interno del servidor"
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
                    "results": results,
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

async def _handle_ai_enrichment(request: SearchRequest) -> dict:
    """Gestiona la fase de IA y devuelve los parámetros enriquecidos."""
    # Valores por defecto
    result = {
        "enriched_query": None,
        "assistant_block": None,
        "effective_used_ai": request.used_ai_assistant,
        "effective_ai_suggestions": request.ai_suggestions
    }

    if not request.use_ai:
        return result

    ai_data = await enrich_query_with_ai(request.query)
    if not ai_data:
        return result

    candidate = (ai_data.get("enriched_query") or "").strip()
    if ai_data.get("is_valid_medical_query", True) and candidate:
        result["enriched_query"] = candidate

    result["assistant_block"] = {
        "diagnosis": ai_data.get("diagnosis", ""),
        "improvement_tips": ai_data.get("improvement_tips", []),
        "enriched_query": ai_data.get("enriched_query", ""),
        "is_valid_medical_query": ai_data.get("is_valid_medical_query", True),
        "processing_time_ms": ai_data.get("processing_time_ms"),
    }
    result["effective_used_ai"] = True
    result["effective_ai_suggestions"] = result["assistant_block"]

    return result

async def _safe_async_log(
    session_id: str | None, user_id: str | None, request: SearchRequest, req: Request,
    top_k: int, formatted_results: list, status: str, search_time_ms: float = 0.0,
    effective_used_ai: bool = False, effective_ai_suggestions: dict | None = None,
    error_message: str | None = None
):
    """Encapsula toda la lógica de logging de forma segura para no bloquear el hilo principal."""
    if not (session_id and user_id):
        return

    try:
        ip_address = req.client.host if getattr(req, "client", None) else "unknown"
        results_for_log = [r.dict() if hasattr(r, 'dict') else r for r in formatted_results]
        
        await register_search_log(
            session_id=session_id,
            user_id=user_id,
            query=request.query,
            top_k=top_k,
            results_count=len(results_for_log),
            results=results_for_log,
            ip_address=ip_address,
            status=status,
            used_ai_assistant=effective_used_ai,
            ai_suggestions=effective_ai_suggestions,
            search_time_ms=search_time_ms,
            error_message=error_message
        )
    except Exception as e:
        logger.warning(f"No se pudo registrar búsqueda en log-service: {e}")

# ==========================================
# PIPELINE DE BÚSQUEDA CON IA (PRIMERA FASE)
# ==========================================
async def enrich_query_with_ai(query: str) -> Optional[dict]:
    """Primera fase del pipeline de búsqueda con IA.

    Pide al procesador LLM el bloque del asistente (diagnosis + consejos) y el
    texto enriquecido que después se usa para recuperar y re-rankear. Si el LLM
    no está disponible o falla, devuelve None y la búsqueda continúa en modo
    normal (degradación elegante, nunca rompe la clasificación).

    Returns:
        dict con las claves 'diagnosis', 'improvement_tips', 'enriched_query',
        'is_valid_medical_query' o None si no se pudo enriquecer.
    """
    try:
        # 45 s para el enriquecimiento con IA (Gemini puede ser lento). Menor que el
        # timeout del gateway hacia el backend (60 s); si se supera, se hace fallback
        # a la búsqueda sin IA con la consulta original.
        async with httpx.AsyncClient(timeout=45.0) as client:
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


@app.post("/search", response_model=SearchResponse, responses={503: {"description": "Search engine not initialized"}, 500: {"description": INTERNAL_ERROR_DETAIL}})
async def search_diagnosis(
    request: SearchRequest, 
    req: Request, 
    background_tasks: BackgroundTasks,
    session_id: Annotated[str | None, Header()] = None, 
    user_id: Annotated[str | None, Header()] = None
):
    """Endpoint principal para buscar diagnósticos"""
    
    if not search_engine:
        raise HTTPException(status_code=503, detail="El motor de búsqueda no está inicializado")
    
    start_time = time.perf_counter()
    session_id = session_id or req.headers.get("x-session-id")
    user_id = user_id or req.headers.get("x-user-id")
    
    # Calcular top_k de forma limpia
    requested_top_k = request.top_k if request.top_k and request.top_k > 0 else 5
    top_k = min(requested_top_k, 20)

    try:
        # 1. Pipeline de IA extraído
        ai_params = await _handle_ai_enrichment(request)

        # 2. Búsqueda principal
        results = search_engine.search(
            request.query, 
            top_k=top_k, 
            enriched_query=ai_params["enriched_query"]
        )
        logger.info("Búsqueda completada: %d resultados (IA=%s)", len(results), request.use_ai)

        # 3. Formateo y tiempos
        formatted_results = format_search_results(results)
        search_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 4. Delegar el guardado del log a BackgroundTasks (Ruta de Éxito)
        background_tasks.add_task(
            _safe_async_log, session_id, user_id, request, req, top_k,
            formatted_results, "success", search_time_ms,
            ai_params["effective_used_ai"], ai_params["effective_ai_suggestions"]
        )
        
        return SearchResponse(
            results=formatted_results,
            query=request.query,
            count=len(formatted_results),
            used_ai=request.use_ai,
            search_time_ms=search_time_ms,
            assistant=ai_params["assistant_block"]
        )
    
    except Exception as e:
        # Delegar el guardado del log a BackgroundTasks
        background_tasks.add_task(
            _safe_async_log, session_id, user_id, request, req, top_k,
            [], "error", 0.0, request.used_ai_assistant, request.ai_suggestions, str(e)
        )
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
