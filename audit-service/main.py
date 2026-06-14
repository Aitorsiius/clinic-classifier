"""
Servicio de Auditoría - CIE-10 Classifier

Microservicio responsable de:
- Auditar diagnósticos contra códigos CIE-10 asignados
- Generar reportes
- Exportar reportes en diferentes formatos
"""

import re

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import httpx
import os
import uvicorn
from datetime import datetime, timezone
from enum import Enum
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from typing import Annotated
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from fastapi import BackgroundTasks

# Importar módulo de auditoría
from audit import (
    CodeAuditor, 
    DiagnosisRecord,
    GatewaySearchEngine
)

# ==========================================
# CONFIGURACIÓN
# ==========================================
AUDIT_SERVICE_PORT = int(os.getenv("AUDIT_SERVICE_PORT", "8005"))
API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "http://localhost:3000")
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INTERNAL_ERROR_DETAIL = "Internal server error"
BACKEND_UNAVAILABLE_DETAIL = "Backend service unavailable"

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class DiscrepancyType(str, Enum):
    """Tipos de discrepancias detectadas"""
    CORRECT = "coincidencia"
    PARTIAL_MATCH = "parcialmente"
    MISMATCH = "no_coincidencia"

class AuditRecordRequest(BaseModel):
    """Solicitud de auditoría para un registro individual"""
    diagnosis_text: str
    assigned_code: str
    patient_id: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None

class AuditBatchRequest(BaseModel):
    """Solicitud de auditoría para lote de registros"""
    records: List[AuditRecordRequest]
    algorithm: Optional[str] = "algoritmo1"
    top_k: Optional[int] = 5
    # Ejecuta la auditoría a través del pipeline de búsqueda con IA.
    use_ai: bool = False

class AuditResult(BaseModel):
    """Resultado individual de auditoría"""
    patient_id: str
    diagnosis_text: str
    assigned_code: str
    suggested_code: str
    discrepancy_type: str
    confidence_score: float
    match_score: float
    explanation: str
    alternative_codes: List[str]

class AuditReportResponse(BaseModel):
    """Respuesta de reporte de auditoría"""
    audit_id: str
    timestamp: str
    total_records: int
    total_correct: int
    total_partial_match: int
    total_mismatch: int
    conformity_percentage: float
    top_k: Optional[int] = 5
    # Tiempo total (ms) del lote de auditoría (con o sin IA).
    total_time_ms: Optional[float] = None
    findings: List[AuditResult]

# ==========================================
# FUNCIONES AUXILIARES
# ==========================================

def verify_token(authorization: str = Header(None)):
    """
    Verifica el token JWT del header Authorization
    
    Args:
        authorization: Header Authorization
        
    Returns:
        Email del usuario si el token es válido
        
    Raises:
        HTTPException: Si el token es inválido o falta
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid auth scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    try:
        with httpx.Client() as client:
            response = client.post(
                f"{API_GATEWAY_URL}/auth/verify",
                json={"token": token},
                timeout=5
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid token")
            
            data = response.json()
            if not data.get("valid"):
                raise HTTPException(status_code=401, detail="Invalid token")
            
            return data.get("email")
    except httpx.RequestError:
        raise HTTPException(status_code=500, detail="Authentication service unavailable")
    
def _build_diagnosis_records(records) -> list[DiagnosisRecord]:
    """Convierte los registros del request a los modelos de dominio."""
    return [
        DiagnosisRecord(
            patient_id=r.patient_id or f"PAT{i:04d}",
            diagnosis_text=r.diagnosis_text,
            assigned_code=r.assigned_code,
            age=r.age,
            sex=r.sex
        )
        for i, r in enumerate(records)
    ]

def _format_audit_result(report, top_k: int) -> dict:
    """Convierte el reporte interno al formato de respuesta JSON."""
    return {
        "audit_id": report.audit_id,
        "timestamp": report.timestamp.isoformat(),
        "total_records": report.total_records,
        "total_correct": report.total_correct,
        "total_partial_match": report.total_partial_match,
        "total_mismatch": report.total_mismatch,
        "conformity_percentage": report.conformity_percentage,
        "top_k": top_k,
        "total_time_ms": round(report.total_time_ms, 2),
        "findings": [
            {
                "patient_id": f.patient_id,
                "diagnosis_text": f.diagnosis_text,
                "assigned_code": f.assigned_code,
                "suggested_code": f.suggested_code,
                "discrepancy_type": f.discrepancy_type.value,
                "confidence_score": f.confidence_score,
                "match_score": f.match_score,
                "explanation": f.explanation,
                "alternative_codes": f.alternative_codes
            }
            for f in report.findings
        ]
    }

def _build_audit_response(report, top_k: int) -> AuditReportResponse:
    """Convierte el reporte interno al modelo Pydantic de respuesta."""
    findings = [
        AuditResult(
            patient_id=f.patient_id,
            diagnosis_text=f.diagnosis_text,
            assigned_code=f.assigned_code,
            suggested_code=f.suggested_code,
            discrepancy_type=f.discrepancy_type.value,
            confidence_score=f.confidence_score,
            match_score=f.match_score,
            explanation=f.explanation,
            alternative_codes=f.alternative_codes
        )
        for f in report.findings
    ]
    
    return AuditReportResponse(
        audit_id=report.audit_id,
        timestamp=report.timestamp.isoformat(),
        total_records=report.total_records,
        total_correct=report.total_correct,
        total_partial_match=report.total_partial_match,
        total_mismatch=report.total_mismatch,
        conformity_percentage=report.conformity_percentage,
        top_k=top_k,
        total_time_ms=round(report.total_time_ms, 2),
        findings=findings
    )

async def _log_audit_to_service(report, current_user: str, algorithm: str, top_k: int, use_ai: bool):
    """Envía el log de auditoría al servicio externo de forma asíncrona."""
    if not current_user:
        return
        
    try:
        payload = {
            "session_id": f"audit_session_{report.audit_id}",
            "username": current_user,
            "records_count": report.total_records,
            "algorithm": algorithm,
            "top_k": top_k,
            "use_ai": use_ai,
            "total_time_ms": round(report.total_time_ms, 2),
            "status": "success",
            "details": {
                "total_correct": report.total_correct,
                "total_partial_match": report.total_partial_match,
                "total_mismatch": report.total_mismatch,
                "conformity_percentage": report.conformity_percentage,
                "use_ai": use_ai,
                "total_time_ms": round(report.total_time_ms, 2),
                "findings": [
                    {
                        "patient_id": f.patient_id,
                        "diagnosis_text": f.diagnosis_text,
                        "assigned_code": f.assigned_code,
                        "suggested_code": f.suggested_code,
                        "discrepancy_type": f.discrepancy_type.value if hasattr(f.discrepancy_type, 'value') else f.discrepancy_type,
                        "confidence_score": f.confidence_score,
                        "match_score": f.match_score,
                        "explanation": f.explanation,
                        "alternative_codes": f.alternative_codes
                    }
                    for f in report.findings
                ]
            }
        }
        async with httpx.AsyncClient() as client:
            await client.post(f"{LOG_SERVICE_URL}/audits", json=payload, timeout=5)
    except Exception as e:
        logger.warning(f"No se pudo registrar auditoría en log-service: {e}")

# ==========================================
# INICIALIZACIÓN FASTAPI
# ==========================================

app = FastAPI(
    title="Audit Service - CIE-10 Classifier",
    description="Servicio de auditoría para CIE-10 Classifier",
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
        "service": "audit-service",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/audit/batch-stream", tags=["Audit"])
async def audit_batch_stream(
    request: AuditBatchRequest,
    current_user: Annotated[str, Depends(verify_token)]
):
    """Realiza una auditoría de lote de registros con progreso en tiempo real via SSE"""
    
    async def event_generator():
        try:
            # 1. Preparar datos usando el helper
            diagnosis_records = _build_diagnosis_records(request.records)
            
            # 2. Configurar la comunicación asíncrona
            progress_queue = asyncio.Queue()
            loop = asyncio.get_running_loop() 
            
            def progress_callback(current: int, total: int):
                event_data = {
                    'type': 'progress', 
                    'current': current, 
                    'total': total, 
                    'percentage': int((current / total) * 100)
                }
                loop.call_soon_threadsafe(progress_queue.put_nowait, event_data)

            # 3. Lanzar la auditoría en segundo plano
            search_engine = GatewaySearchEngine(API_GATEWAY_URL)
            auditor = CodeAuditor(search_engine)
            
            with ThreadPoolExecutor(max_workers=1) as executor:
                audit_task = loop.run_in_executor(
                    executor,
                    lambda: auditor.audit_batch(
                        diagnosis_records, 
                        algorithm=request.algorithm or "algoritmo1",
                        top_k=request.top_k or 5, 
                        progress_callback=progress_callback,
                        use_ai=request.use_ai
                    )
                )
                
                # 4. Bucle de streaming simplificado
                while not audit_task.done():
                    try:
                        progress_event = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                        yield f"data: {json.dumps(progress_event)}\n\n"
                    except asyncio.TimeoutError:
                        continue
                
                # 5. Vaciar cualquier evento residual en la cola antes de cerrar
                while not progress_queue.empty():
                    yield f"data: {json.dumps(progress_queue.get_nowait())}\n\n"
                
            # 6. Formatear y enviar resultado final usando el helper
                report = audit_task.result()
                result_json = _format_audit_result(report, request.top_k or 5)
                yield f"data: {json.dumps({'type': 'complete', 'result': result_json})}\n\n"
                
        except Exception as e:
            logger.exception("Error durante el streaming de auditoría: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': INTERNAL_ERROR_DETAIL})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/audit/batch", response_model=AuditReportResponse, tags=["Audit"], responses={503: {"description": BACKEND_UNAVAILABLE_DETAIL}, 500: {"description": INTERNAL_ERROR_DETAIL}})
async def audit_batch(
    request: AuditBatchRequest,
    current_user: Annotated[str, Depends(verify_token)],
    background_tasks: BackgroundTasks
):
    """Realiza una auditoría de lote de registros."""
    try:
        # 1. Extraer configuraciones y mapear registros
        top_k = request.top_k or 5
        algorithm = request.algorithm or "algoritmo1"
        diagnosis_records = _build_diagnosis_records(request.records)
        
        # 2. Ejecutar auditoría localmente
        search_engine = GatewaySearchEngine(API_GATEWAY_URL)
        auditor = CodeAuditor(search_engine)
        report = auditor.audit_batch(
        diagnosis_records, 
            algorithm=algorithm, 
            top_k=top_k, 
            use_ai=request.use_ai
        )
        
        # 3. Delegar el log a una tarea en segundo plano 
        background_tasks.add_task(
            _log_audit_to_service,
            report=report,
            current_user=current_user,
            algorithm=algorithm,
            top_k=top_k,
            use_ai=request.use_ai
        )
        
        # 4. Formatear y retornar
        return _build_audit_response(report, top_k)
        
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.warning("Backend no disponible durante la auditoría: %s", e)
        raise HTTPException(status_code=503, detail=BACKEND_UNAVAILABLE_DETAIL)
    except Exception as e:
        logger.exception("Error interno durante la auditoría: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.post("/audit/record", response_model=AuditResult, tags=["Audit"], responses={503: {"description": BACKEND_UNAVAILABLE_DETAIL}, 
                                                                                  500: {"description": INTERNAL_ERROR_DETAIL}})
async def audit_record(
    request: AuditRecordRequest,
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Audita un registro individual
    
    Args:
        request: Registro a auditar
        current_user: Email del usuario autenticado
        
    Returns:
        AuditResult con el resultado de la auditoría
        
    Raises:
        HTTPException: Si hay error en la auditoría
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_GATEWAY_URL}/api/audit/record",
                json=request.model_dump(),
                timeout=15
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Audit processing failed")
        
        result = response.json()
        
        return AuditResult(**result)
    
    except HTTPException:
        raise
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Backend service unavailable")
    except Exception as e:
        logger.exception("Error interno auditando registro individual: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

@app.get("/audit/{audit_id}", response_model=AuditReportResponse, tags=["Audit"], responses={503: {"description": BACKEND_UNAVAILABLE_DETAIL}, 
                                                                                             500: {"description": INTERNAL_ERROR_DETAIL}, 
                                                                                             404: {"description": "Audit report not found"}})
async def get_audit_report(
    audit_id: str,
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Obtiene un reporte de auditoría por su ID
    
    Args:
        audit_id: ID de la auditoría
        current_user: Email del usuario autenticado
        
    Returns:
        AuditReportResponse del reporte solicitado
        
    Raises:
        HTTPException: Si el reporte no existe
    """
    try:
        safe_audit_id = urllib.parse.quote(audit_id, safe="")
        # Obtener del backend a través del gateway
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_GATEWAY_URL}/api/audit/{safe_audit_id}",
                timeout=10
            )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Audit report not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error fetching report")
        
        result = response.json()
        return AuditReportResponse(**result)
    
    except HTTPException:
        raise
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail=BACKEND_UNAVAILABLE_DETAIL)
    except Exception as e:
        logger.exception("Error interno obteniendo reporte de auditoría: %s", e)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=AUDIT_SERVICE_PORT,
        log_level="info"
    )
