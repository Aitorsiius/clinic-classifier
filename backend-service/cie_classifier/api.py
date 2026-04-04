from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from datetime import datetime
from main import MedicalSearchEngine
import csv
import io

# ==========================================
# MODELOS PYDANTIC
# ==========================================

class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    algorithm: Optional[str] = "hybrid"


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
# INICIALIZACIÓN FASTAPI
# ==========================================

app = FastAPI(
    title="CIE-10 Classifier API",
    description="API para clasificación de diagnósticos médicos usando CIE-10",
    version="1.0.0"
)

# Configuración CORS para permitir peticiones desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialización del motor de búsqueda
print("Inicializando Motor de Búsqueda...")
try:
    search_engine = MedicalSearchEngine()
    print("Motor de Búsqueda listo")
except Exception as e:
    print(f"Error al inicializar el motor: {e}")
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
async def search_diagnosis(request: SearchRequest):
    """
    Endpoint principal para buscar diagnósticos
    
    Args:
        request: Objeto con la query y top_k opcional
    
    Returns:
        SearchResponse con los resultados encontrados
    """
    if not search_engine:
        raise HTTPException(status_code=503, detail="Search engine not initialized")
    
    try:
        # Obtener el top_k del request, con un máximo de 20
        requested_top_k = request.top_k if request.top_k and request.top_k > 0 else 5
        top_k = min(requested_top_k, 20)
        
        print(f"[SEARCH DEBUG] Query: '{request.query}'")
        print(f"[SEARCH DEBUG] request.top_k raw value: {request.top_k} (type: {type(request.top_k)})")
        print(f"[SEARCH DEBUG] Calculated top_k: {top_k}")
        
        # Realizar búsqueda
        results = search_engine.search(request.query, top_k=top_k)
        print(f"[SEARCH DEBUG] Resultados obtenidos del motor: {len(results)} resultados")
        
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
        
        return SearchResponse(
            results=formatted_results,
            query=request.query,
            count=len(formatted_results)
        )
    
    except Exception as e:
        print(f"Error en búsqueda: {e}")
        raise HTTPException(status_code=500, detail=f"Error en búsqueda: {str(e)}")

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
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    import os
    port = int(os.getenv("BACKEND_PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
