"""
Servicio de Auditoría - CIE-10 Classifier

Microservicio responsable de:
- Auditar diagnósticos contra códigos CIE-10 asignados
- Generar reportes
- Exportar reportes en diferentes formatos
"""

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
    current_user: str = Depends(verify_token)
):
    """
    Realiza una auditoría de lote de registros con progreso en tiempo real via SSE
    
    Devuelve eventos con progreso conforme se procesan los registros
    
    Args:
        request: Lote de registros a auditar
        current_user: Email del usuario autenticado
        
    Yields:
        Eventos SSE con progreso y resultado final
    """
    async def event_generator():
        try:
            # 1. Crear records para auditoría
            diagnosis_records = [
                DiagnosisRecord(
                    patient_id=r.patient_id or f"PAT{i:04d}",
                    diagnosis_text=r.diagnosis_text,
                    assigned_code=r.assigned_code,
                    age=r.age,
                    sex=r.sex
                )
                for i, r in enumerate(request.records)
            ]
            
            # Cola para comunicación entre threads
            progress_queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            
            # Callback para enviar eventos de progreso
            def progress_callback(current: int, total: int):
                # Enviar evento de progreso a la cola
                try:
                    asyncio.run_coroutine_threadsafe(
                        progress_queue.put({'type': 'progress', 'current': current, 'total': total, 'percentage': int((current / total) * 100)}), 
                        loop
                    )
                except Exception:
                    pass

            # Procesar la auditoría en un thread pool para no bloquear el event loop
            search_engine = GatewaySearchEngine(API_GATEWAY_URL)
            auditor = CodeAuditor(search_engine)
            
            # Ejecutar auditoría en thread separado
            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)
            
            # Task para procesar auditoría
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
            
            # Leer eventos de progreso mientras se procesa
            report = None
            while report is None:
                try:
                    # Intentar obtener evento de progreso con timeout
                    progress_event = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                    yield f"data: {json.dumps(progress_event)}\n\n"
                except asyncio.TimeoutError:
                    # Verificar si la auditoría ya terminó
                    if audit_task.done():
                        report = audit_task.result()
                        break
                    continue
            
            # 3. Formatear respuesta final
            findings = [
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
            
            result = {
                "audit_id": report.audit_id,
                "timestamp": report.timestamp.isoformat(),
                "total_records": report.total_records,
                "total_correct": report.total_correct,
                "total_partial_match": report.total_partial_match,
                "total_mismatch": report.total_mismatch,
                "conformity_percentage": report.conformity_percentage,
                "top_k": request.top_k or 5,
                "total_time_ms": round(report.total_time_ms, 2),
                "findings": findings
            }
            
            # Enviar resultado final
            yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
            
        except Exception as e:
            logger.exception("Error durante el streaming de auditoría: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Internal server error'})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/audit/batch", response_model=AuditReportResponse, tags=["Audit"])
async def audit_batch(
    request: AuditBatchRequest,
    current_user: str = Depends(verify_token)
):
    """
    Realiza una auditoría de lote de registros
    
    El flujo es:
    1. Recibe lote de registros (diagnosis_text, assigned_code)
    2. Para cada uno, hace búsqueda semántica en el backend
    3. Compara código asignado con código sugerido
    4. Retorna reporte con hallazgos
    
    Args:
        request: Lote de registros a auditar
        current_user: Email del usuario autenticado
        
    Returns:
        AuditReportResponse con los resultados de la auditoría
    """
    try:
        # 1. Crear records para auditoría
        diagnosis_records = [
            DiagnosisRecord(
                patient_id=r.patient_id or f"PAT{i:04d}",
                diagnosis_text=r.diagnosis_text,
                assigned_code=r.assigned_code,
                age=r.age,
                sex=r.sex
            )
            for i, r in enumerate(request.records)
        ]
        
        # 2. Para cada registro, obtener resultados de búsqueda del backend
        search_results_map = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for record in diagnosis_records:
                try:
                    # Buscar a través del gateway
                    response = await client.post(
                        f"{API_GATEWAY_URL}/api/search",
                        json={"query": record.diagnosis_text, "top_k": request.top_k or 5},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        search_data = response.json()
                        search_results_map[record.diagnosis_text] = search_data.get("results", [])
                    else:
                        search_results_map[record.diagnosis_text] = []
                except Exception:
                    search_results_map[record.diagnosis_text] = []
        
        # 3. Ejecutar auditoría localmente
        search_engine = GatewaySearchEngine(API_GATEWAY_URL)
        auditor = CodeAuditor(search_engine)
        report = auditor.audit_batch(diagnosis_records, algorithm=request.algorithm or "algoritmo1", top_k=request.top_k or 5, use_ai=request.use_ai)
        
        # 4. Formatear respuesta
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
        
        result = AuditReportResponse(
            audit_id=report.audit_id,
            timestamp=report.timestamp.isoformat(),
            total_records=report.total_records,
            total_correct=report.total_correct,
            total_partial_match=report.total_partial_match,
            total_mismatch=report.total_mismatch,
            conformity_percentage=report.conformity_percentage,
            top_k=request.top_k or 5,
            total_time_ms=round(report.total_time_ms, 2),
            findings=findings
        )
        
        # Registrar auditoría en log-service
        if current_user:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{LOG_SERVICE_URL}/audits",
                        json={
                            "session_id": "audit_session_" + report.audit_id,
                            "username": current_user,
                            "records_count": len(diagnosis_records),
                            "algorithm": request.algorithm or "algoritmo1",
                            "top_k": request.top_k or 5,
                            "use_ai": request.use_ai,
                            "total_time_ms": round(report.total_time_ms, 2),
                            "status": "success",
                            "details": {
                                "total_correct": report.total_correct,
                                "total_partial_match": report.total_partial_match,
                                "total_mismatch": report.total_mismatch,
                                "conformity_percentage": report.conformity_percentage,
                                "use_ai": request.use_ai,
                                "total_time_ms": round(report.total_time_ms, 2),
                                "findings": [
                                    {
                                        "patient_id": f.patient_id,
                                        "diagnosis_text": f.diagnosis_text,
                                        "assigned_code": f.assigned_code,
                                        "suggested_code": f.suggested_code,
                                        "discrepancy_type": f.discrepancy_type,
                                        "confidence_score": f.confidence_score,
                                        "match_score": f.match_score,
                                        "explanation": f.explanation,
                                        "alternative_codes": f.alternative_codes
                                    }
                                    for f in report.findings
                                ]
                            }
                        },
                        timeout=5
                    )
            except Exception as e:
                logger.warning(f"No se pudo registrar auditoría en log-service: {e}")
        
        return result
        
    except HTTPException:
        raise
    except httpx.RequestError as e:
        logger.warning("Backend no disponible durante la auditoría: %s", e)
        raise HTTPException(status_code=503, detail="Backend service unavailable")
    except Exception as e:
        logger.exception("Error interno durante la auditoría: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/audit/record", response_model=AuditResult, tags=["Audit"])
async def audit_record(
    request: AuditRecordRequest,
    current_user: str = Depends(verify_token)
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
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/audit/{audit_id}", response_model=AuditReportResponse, tags=["Audit"])
async def get_audit_report(
    audit_id: str,
    current_user: str = Depends(verify_token)
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
        # Obtener del backend a través del gateway
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_GATEWAY_URL}/api/audit/{audit_id}",
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
        raise HTTPException(status_code=503, detail="Backend service unavailable")
    except Exception as e:
        logger.exception("Error interno obteniendo reporte de auditoría: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

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
