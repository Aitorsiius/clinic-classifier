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
        raise HTTPException(status_code=500, detail="Internal server error")

def analyze_query(query: str) -> dict:
    """Analiza la consulta"""
    prompt = f"""Analiza esta consulta médica y extrae SOLO términos clínicos en lenguaje natural.
IMPORTANTE: 
- Solo incluye síntomas, diagnósticos y hallazgos REALES mencionados o claramente implícitos
- NO inventes síntomas adicionales ni des descripciones genéricas
- NUNCA incluyas códigos, números o abreviaturas - usa SOLO lenguaje natural médico
- search_keywords debe contener SOLO términos médicos simples en español que se buscarían naturalmente
- Sé conciso y específico

Devuelve SOLO JSON sin explicaciones:
{{"primary_symptoms": [], "secondary_symptoms": [], "key_findings": [], "search_keywords": [], "clinical_context": ""}}

Consulta: {query}"""
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
    prompt = f"""Corrige y normaliza esta consulta médica usando lenguaje natural médico estándar.
IMPORTANTE:
- Reemplaza ALL las abreviaturas, acrónimos y siglas con términos completos en español
- Traduce siglas como: HTA→Hipertensión arterial, DM→Diabetes mellitus, IAM→Infarto agudo de miocardio, etc.
- Usa SOLO lenguaje natural - NUNCA incluyas códigos, números o referencias a clasificaciones
- Ordena los términos de forma lógica (síntoma primario primero, complicaciones después)
- NO inventes diagnósticos o síntomas adicionales
- Mantén SOLO lo que el usuario menciona explícitamente

Devuelve SOLO JSON:
{{"corrected_query": "", "corrections": {{}}, "is_valid_medical_query": true}}

Consulta: {query}"""
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
      - diagnostico: interpretación clínica en lenguaje natural de lo que el
        usuario ha introducido.
      - consejos_mejora: información clínica AUSENTE que, de aportarse, afinaría
        la clasificación (lateralidad, temporalidad del contacto, agudo/crónico,
        etiología, localización anatómica, etc.).
      - enriched_query: texto técnico DENSO en el estilo de las descripciones
        CIE-10-ES (descripción clínica + sinónimos + términos de inclusión) que
        se enviará al bi-encoder y al cross-encoder ya existentes. NO incluye
        códigos: solo terminología clínica estándar para mejorar el "match".

    El objetivo es cerrar la brecha semántica entre el lenguaje coloquial del
    usuario y el texto técnico-jerárquico indexado en la base vectorial. La IA
    se usa SOLO en esta fase; el re-ranking lo sigue haciendo el cross-encoder.
    """
    prompt = f"""Eres un experto en codificación clínica CIE-10-ES. Tu tarea NO es asignar el
código final, sino TRADUCIR y ENRIQUECER el texto del usuario para que un buscador
semántico (embeddings + cross-encoder) encuentre los códigos correctos.

Las descripciones de la base de datos siguen un estilo técnico y jerárquico, por
ejemplo: "ENFERMEDADES INFECCIOSAS INTESTINALES Cólera debido a Vibrio cholerae 01".
Los códigos muy parecidos se diferencian por EJES DE DESEMPATE: localización
anatómica, lateralidad (derecho/izquierdo/bilateral), temporalidad del contacto
(inicial/sucesivo/secuela), agudo/crónico, etiología, severidad y presencia o
ausencia de complicaciones.

INSTRUCCIONES:
1. "diagnostico": redacta una frase clínica técnica, neutra y precisa de lo que
   presenta el paciente. NO inventes datos que el usuario no haya dado; si algo es
   ambiguo, no lo afirmes.
2. "enriched_query": un párrafo DENSO que imite el estilo de las descripciones
   CIE-10-ES (descripción clínica + sinónimos médicos + términos de inclusión).
   Debe sonar a manual de codificación, NO a lenguaje coloquial. Usa terminología
   estándar en español. NUNCA incluyas códigos, números de clasificación ni siglas.
3. "consejos_mejora": revisa la consulta y detecta qué INFORMACIÓN CLAVE falta para
   elegir un código único. Fíjate específicamente en estos ejes (menciona solo los
   que NO estén ya especificados por el usuario):
   - Localización anatómica exacta (hueso/órgano y región: proximal, distal, lóbulo,
     segmento, cara, etc.).
   - Lateralidad: derecho, izquierdo o bilateral.
   - Temporalidad del contacto asistencial: contacto inicial, contacto sucesivo o
     secuela (clave en traumatismos; cambia el último carácter del código).
   - Evolución: agudo, crónico o reagudizado; tiempo de evolución.
   - Etiología o causa: traumática, infecciosa (agente concreto), tumoral, isquémica,
     idiopática, medicamentosa, etc.
   - Severidad o grado: leve/moderado/grave, estadio, % afectado, escala clínica.
   - Complicaciones o manifestaciones asociadas (con/sin complicación específica).
   - Contexto fisiológico cuando aplique: trimestre de embarazo, edad gestacional,
     tipo de parto, etc.
   Para cada dato ausente RELEVANTE, redacta UN consejo accionable y breve dirigido
   al usuario ("Indica…", "Especifica…", "Confirma…"). Ordena los consejos por
   impacto en el código (lateralidad y temporalidad primero). Como máximo 5 consejos.
   Si la consulta ya define todos los ejes relevantes, devuelve una lista vacía.
4. "is_valid_medical_query": false si el texto no es una consulta clínica
   interpretable (en ese caso deja "diagnostico" y "enriched_query" vacíos y
   "consejos_mejora" vacío).
5. NO devuelvas códigos CIE-10. Responde EXCLUSIVAMENTE con el JSON, sin texto extra.

Formato de salida (JSON estricto):
{{"diagnostico": "", "enriched_query": "", "consejos_mejora": [], "is_valid_medical_query": true}}

EJEMPLO (referencia de estilo y nivel de detalle):
Consulta del usuario: "fractura muñeca izquierda, primera vez que viene"
Respuesta:
{{"diagnostico": "Fractura cerrada del extremo distal del radio izquierdo, primer contacto asistencial.", "enriched_query": "Fractura de la extremidad inferior del radio izquierdo, fractura distal de antebrazo, fractura de la muñeca, lesión traumática ósea de la región distal del radio, contacto inicial para fractura cerrada.", "consejos_mejora": ["Confirma el tipo de contacto: inicial, sucesivo o secuela (cambia el código).", "Indica si la fractura es abierta o cerrada.", "Especifica si existe desplazamiento o conminución de los fragmentos.", "Detalla el mecanismo de la lesión (caída, traumatismo directo, etc.)."], "is_valid_medical_query": true}}

Consulta del usuario: {query}"""
    response = call_gemini(prompt)
    fallback = {
        "diagnostico": "",
        "enriched_query": "",
        "consejos_mejora": [],
        "is_valid_medical_query": True,
    }
    try:
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            data = json.loads(response[json_start:json_end])
            # Normalizar tipos por robustez frente a respuestas inesperadas.
            consejos = data.get("consejos_mejora", [])
            if isinstance(consejos, str):
                consejos = [consejos] if consejos.strip() else []
            elif not isinstance(consejos, list):
                consejos = []
            return {
                "diagnostico": str(data.get("diagnostico", "") or "").strip(),
                "enriched_query": str(data.get("enriched_query", "") or "").strip(),
                "consejos_mejora": [str(c).strip() for c in consejos if str(c).strip()],
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

    Devuelve el bloque del asistente (diagnostico + consejos_mejora) y el
    enriched_query que alimentará al bi-encoder y al cross-encoder existentes.
    """
    start_time = time.time()
    assist = ai_search_assist(request.query)
    processing_time_ms = (time.time() - start_time) * 1000
    return {
        "original_query": request.query,
        "diagnostico": assist.get("diagnostico", ""),
        "enriched_query": assist.get("enriched_query", ""),
        "consejos_mejora": assist.get("consejos_mejora", []),
        "is_valid_medical_query": assist.get("is_valid_medical_query", True),
        "processing_time_ms": processing_time_ms,
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=8003, reload=False)
