import os
import json
import time
import glob
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import vertexai
from vertexai.generative_models import GenerativeModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURACIÓN VERTEX AI
# ==========================================
# Buscar archivo JSON de credenciales VertexAI
CREDENTIALS_FILE = None
for json_file in glob.glob("/app/credentials/*.json") + glob.glob("./*.json"):
    if json_file.endswith(".json"):
        CREDENTIALS_FILE = json_file
        break

if CREDENTIALS_FILE:
    # Usar credenciales del archivo JSON
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE
    with open(CREDENTIALS_FILE) as f:
        creds_data = json.load(f)
        PROJECT_ID = creds_data.get("project_id")
else:
    # Fallback a variables de entorno
    PROJECT_ID = os.getenv("ID")

LOCATION = os.getenv("LOCATION", "europe-west1")

if not PROJECT_ID or not LOCATION:
    raise ValueError("PROJECT_ID y LOCATION son requeridos")

# ==========================================
# PROMPTS (externalizados a prompts.json)
# ==========================================
# Las plantillas de prompt viven fuera del código para poder ajustarlas sin
# tocar la lógica. En el JSON cada plantilla se guarda como una LISTA de líneas
# (para que sea legible); aquí se unen con saltos de línea. Cada plantilla
# contiene el marcador `{query}`, que se sustituye por el texto del usuario en
# tiempo de ejecución (usamos str.replace en lugar de str.format para no tener
# que escapar las llaves del JSON de ejemplo del prompt).
QUERY_PLACEHOLDER = "{query}"
PROMPTS_FILE = os.getenv(
    "PROMPTS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")
)
with open(PROMPTS_FILE, encoding="utf-8") as _f:
    _raw_prompts = json.load(_f)
PROMPTS = {
    key: ("\n".join(value) if isinstance(value, list) else value)
    for key, value in _raw_prompts.items()
}
for _key in ("analyze", "correct", "ai_search"):
    if _key not in PROMPTS:
        raise ValueError(f"Falta la plantilla de prompt '{_key}' en {PROMPTS_FILE}")

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

# Inicializar Vertex AI
vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.5-flash")

class QueryRequest(BaseModel):
    query: str

# ==========================================
# LIFESPAN (Startup/Shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("LLM Query Processor - Vertex AI iniciando")
    try:
        model.generate_content("Hola")
        logger.info("Conexión con Vertex AI establecida")
    except Exception as e:
        logger.warning("No se pudo conectar con Vertex AI: %s", e)
    
    yield
    
    # Shutdown
    logger.info("LLM Query Processor - Apagando")

app = FastAPI(
    title="LLM Query Processor - Gemini",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def call_gemini(prompt: str) -> str:
    """Llamada a Vertex AI Generative Model"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        error_str = str(e)
        # Manejar error 429 (quota exceeded) o 403 (permission denied)
        if "429" in error_str or "quota" in error_str.lower():
            raise HTTPException(
                status_code=429, 
                detail="Cuota de Vertex AI agotada. Intenta de nuevo más tarde."
            )
        elif "403" in error_str or "permission" in error_str.lower():
            raise HTTPException(
                status_code=403,
                detail="Permiso denegado. Verifica las credenciales de Vertex AI."
            )
        logger.exception("Error al llamar a Vertex AI: %s", e)
        raise HTTPException(status_code=500, detail="Error interno del servidor")

def analyze_query(query: str) -> dict:
    """Analiza la consulta"""
    prompt = PROMPTS["analyze"].replace(QUERY_PLACEHOLDER, query)
    response = call_gemini(prompt)
    try:
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return json.loads(response[json_start:json_end])
        return {"primary_symptoms": [], "secondary_symptoms": [], "key_findings": [], "search_keywords": [], "clinical_context": ""}
    except Exception:
        return {"primary_symptoms": [], "secondary_symptoms": [], "key_findings": [], "search_keywords": [], "clinical_context": ""}

def correct_query(query: str) -> dict:
    """Corrige y normaliza la consulta: traduce acrónimos, normaliza términos"""
    prompt = PROMPTS["correct"].replace(QUERY_PLACEHOLDER, query)
    response = call_gemini(prompt)
    try:
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return json.loads(response[json_start:json_end])
        return {"corrected_query": query, "corrections": {}, "is_valid_medical_query": True}
    except Exception:
        return {"corrected_query": query, "corrections": {}, "is_valid_medical_query": True}


def ai_search_assist(query: str) -> dict:
    """Primera fase del pipeline de búsqueda con IA.

    Con UNA sola llamada al modelo se obtiene:
      - diagnosis: interpretación clínica en lenguaje natural de lo que el
        usuario ha introducido.
      - improvement_tips: información clínica AUSENTE que, de aportarse, afinaría
        la clasificación (lateralidad, temporalidad del contacto, agudo/crónico,
        etiología, localización anatómica, etc.).
      - enriched_query: ÚNICAMENTE el nombre canónico del diagnóstico en su forma
        base (tal y como figura como TÍTULO en el catálogo CIE-10-ES), SIN sinónimos
        ni términos descriptivos/anatómicos extra, que se enviará al bi-encoder y al
        cross-encoder ya existentes. Cada palabra de más introduce ruido semántico y
        atrae códigos de patologías erróneas; NO incluye códigos.

    El objetivo es cerrar la brecha semántica entre el lenguaje coloquial del
    usuario y el texto técnico-jerárquico indexado en la base vectorial. La IA
    se usa SOLO en esta fase; el re-ranking lo sigue haciendo el cross-encoder.
    """
    prompt = PROMPTS["ai_search"].replace(QUERY_PLACEHOLDER, query)
    response = call_gemini(prompt)
    fallback = {
        "diagnosis": "",
        "enriched_query": "",
        "improvement_tips": [],
        "is_valid_medical_query": True,
    }
    try:
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            data = json.loads(response[json_start:json_end])
            # Normalizar tipos por robustez frente a respuestas inesperadas.
            consejos = data.get("improvement_tips", [])
            if isinstance(consejos, str):
                consejos = [consejos] if consejos.strip() else []
            elif not isinstance(consejos, list):
                consejos = []
            return {
                "diagnosis": str(data.get("diagnosis", "") or "").strip(),
                "enriched_query": str(data.get("enriched_query", "") or "").strip(),
                "improvement_tips": [str(c).strip() for c in consejos if str(c).strip()],
                "is_valid_medical_query": bool(data.get("is_valid_medical_query", True)),
            }
        return fallback
    except Exception:
        return fallback


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-query-processor"}

@app.post("/analyze", responses={429: {"description": "Cuota de Vertex AI agotada"}, 
                                 403: {"description": "Permiso denegado en Vertex AI"}, 
                                 500: {"description": "Internal server error"}})
async def analyze(request: QueryRequest):
    return analyze_query(request.query)

@app.post("/correct", responses={429: {"description": "Cuota de Vertex AI agotada"}, 
                                 403: {"description": "Permiso denegado en Vertex AI"}, 
                                 500: {"description": "Internal server error"}})
async def correct(request: QueryRequest):
    return correct_query(request.query)

@app.post("/process", responses={429: {"description": "Cuota de Vertex AI agotada"}, 
                                 403: {"description": "Permiso denegado en Vertex AI"}, 
                                 500: {"description": "Internal server error"}})
async def process(request: QueryRequest):
    start_time = time.time()
    corrected = correct_query(request.query)
    corrected_query = corrected.get("corrected_query", request.query)
    analysis = analyze_query(corrected_query)
    processing_time_ms = (time.time() - start_time) * 1000
    return {
        "original_query": request.query,
        "corrected_query": corrected_query,
        "analysis": analysis,
        "processing_time_ms": processing_time_ms
    }

@app.post("/ai-search", responses={429: {"description": "Cuota de Vertex AI agotada"}, 
                                   403: {"description": "Permiso denegado en Vertex AI"}, 
                                   500: {"description": "Internal server error"}})
async def ai_search(request: QueryRequest):
    """Primera fase del pipeline de búsqueda con IA (una sola llamada al LLM).

    Devuelve el bloque del asistente (diagnosis + improvement_tips) y el
    enriched_query que alimentará al bi-encoder y al cross-encoder existentes.
    """
    start_time = time.time()
    assist = ai_search_assist(request.query)
    processing_time_ms = (time.time() - start_time) * 1000
    return {
        "original_query": request.query,
        "diagnosis": assist.get("diagnosis", ""),
        "enriched_query": assist.get("enriched_query", ""),
        "improvement_tips": assist.get("improvement_tips", []),
        "is_valid_medical_query": assist.get("is_valid_medical_query", True),
        "processing_time_ms": processing_time_ms,
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=8003, reload=False)
