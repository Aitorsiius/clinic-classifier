import os
import json
import time
import glob
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import uvicorn
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
import google.auth
from google.cloud import aiplatform
import vertexai
from vertexai.generative_models import GenerativeModel

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

# Inicializar Vertex AI
vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.5-flash")

MEDICAL_ACRONYMS = {
    # Cardiología
    "IAM": "Infarto Agudo de Miocardio",
    "HTA": "Hipertensión Arterial",
    "ICC": "Insuficiencia Cardíaca Congestiva",
    "ICA": "Insuficiencia Cardíaca Aguda",
    "ACV": "Accidente Cerebrovascular",
    "TSV": "Taquicardia Supraventricular",
    "FA": "Fibrilación Auricular",
    "BAV": "Bloqueo Auriculoventricular",
    "EAM": "Evento Agudo de Miocardio",
    
    # Endocrinología
    "DM": "Diabetes Mellitus",
    "DMT1": "Diabetes Mellitus Tipo 1",
    "DMT2": "Diabetes Mellitus Tipo 2",
    "HbA1c": "Hemoglobina Glucosilada",
    
    # Respiratorio
    "EPOC": "Enfermedad Pulmonar Obstructiva Crónica",
    "SDRA": "Síndrome de Dificultad Respiratoria Aguda",
    "TEP": "Tromboembolismo Pulmonar",
    "NAC": "Neumonía Adquirida en la Comunidad",
    "TIRS": "Síndrome de Respuesta Inflamatoria Sistémica",
    "TBC": "Tuberculosis",
    
    # Gastrointestinal
    "EII": "Enfermedad Inflamatoria Intestinal",
    "EC": "Enfermedad de Crohn",
    "RCU": "Retocolitis Ulcerosa",
    "ERGE": "Enfermedad por Reflujo Gastroesofágico",
    "GEA": "Gastroenteritis Aguda",
    "PUD": "Úlcera Péptica",
    
    # Neurología
    "ELA": "Esclerosis Lateral Amiotrófica",
    "EM": "Esclerosis Múltiple",
    "EA": "Enfermedad de Alzheimer",
    "EP": "Enfermedad de Parkinson",
    "TCE": "Traumatismo Craneoencefálico",
    "SGB": "Síndrome de Guillain-Barré",
    "HSV": "Virus del Herpes Simple",
    
    # Hematología
    "LLA": "Leucemia Linfoblástica Aguda",
    "LLC": "Leucemia Linfocítica Crónica",
    "LM": "Leucemia Mieloide",
    "DIC": "Coagulopatía de Consumo",
    "PTI": "Púrpura Trombocitopénica Idiopática",
    
    # Oncología
    "CA": "Cáncer",
    "CAP": "Cáncer de Próstata",
    "CAM": "Cáncer de Mama",
    "CCP": "Cáncer Colorrectal",
    "CMC": "Carcinoma Medular de Colon",
    "CHC": "Carcinoma Hepatocelular",
    "LQMA": "Linfoma de Hodgkin",
    
    # Infectología
    "VIH": "Virus de Inmunodeficiencia Humana",
    "SIDA": "Síndrome de Inmunodeficiencia Adquirida",
    "CMV": "Citomegalovirus",
    "FAA": "Fiebre Amarilla",
    "DVG": "Dengue",
    "CVD": "COVID-19",
    "ITU": "Infección del Tracto Urinario",
    "UPD": "Sepsis",
    
    # Nefología
    "IRA": "Insuficiencia Renal Aguda",
    "IRC": "Insuficiencia Renal Crónica",
    "ERC": "Enfermedad Renal Crónica",
    "GN": "Glomerulonefritis",
    "SN": "Síndrome Nefrótico",
    "GES": "Glomerulonefritis Extracapilar Rápidamente Progresiva",
    
    # Reumatología
    "AR": "Artritis Reumatoide",
    "LES": "Lupus Eritematoso Sistémico",
    "AE": "Artritis Espondilitis",
    "ESC": "Esclerodermia",
    "SAE": "Síndrome Antifosfolípido",
    "GCA": "Arteritis Temporal",
    
    # Endocrino-Metabólico
    "TSH": "Hormona Estimulante de la Tiroides",
    "T3": "Triyodotironina",
    "T4": "Tiroxina",
    "HT": "Hipotiroidismo",
    "HTS": "Hipertiroidismo",
    "OB": "Obesidad",
    
    # Dermatología
    "TM": "Melanoma",
    "PEP": "Psoriasis",
    "ED": "Eczema Dermatitis",
    "UI": "Urticaria",
    "AE": "Acné",
    
    # Oftalmología
    "GLC": "Glaucoma",
    "DRP": "Degeneración Macular Relacionada con la Edad",
    "RD": "Retinopatía Diabética",
    "OAL": "Oftalmología",
    "CV": "Cataratas",
    
    # Otorrinolaringología
    "ORL": "Otorrinolaringología",
    "OMS": "Otitis Media Supurativa",
    "SV": "Sinusitis",
    "FA": "Faringitis",
    "LA": "Laringitis",
    
    # Ginecología-Obstetricia
    "EPI": "Enfermedad Pélvica Inflamatoria",
    "EOG": "Endometriosis",
    "SOP": "Síndrome de Ovario Poliquístico",
    "VPH": "Virus del Papiloma Humano",
    "FIC": "Fibromas",
    "EME": "Embarazo Ectópico",
    
    # Pediatría
    "SDR": "Síndrome de Dificultad Respiratoria",
    "DBP": "Displasia Broncopulmonar",
    "PIC": "Parálisis Infantil Cerebral",
    "EA": "Enfermedad de Perthes",
    
    # Psiquiatría
    "TDM": "Trastorno Depresivo Mayor",
    "TA": "Trastorno de Ansiedad",
    "TDAH": "Trastorno por Déficit de Atención e Hiperactividad",
    "TAB": "Trastorno Afectivo Bipolar",
    "TPA": "Trastorno de Personalidad Antisocial",
    "TDC": "Trastorno de Conducta",
    
    # Anestesiología
    "ASA": "Clasificación de Riesgo Anestésico",
    "UCI": "Unidad de Cuidados Intensivos",
    "VMI": "Ventilación Mecánica Invasiva",
    "EMG": "Electromiografía",
    
    # General
    "RX": "Radiografía",
    "TC": "Tomografía Computarizada",
    "RM": "Resonancia Magnética",
    "US": "Ultrasonido",
    "EKG": "Electrocardiograma",
    "PCR": "Proteína C Reactiva",
    "VSG": "Velocidad de Sedimentación Globular",
    "FC": "Frecuencia Cardíaca",
    "FA": "Frecuencia Alimentaria",
    "PA": "Presión Arterial",
    "PAS": "Presión Arterial Sistólica",
    "PAD": "Presión Arterial Diastólica",
    "FR": "Frecuencia Respiratoria",
    "Sat": "Saturación de Oxígeno",
    "IMC": "Índice de Masa Corporal",
}

class QueryRequest(BaseModel):
    query: str

# ==========================================
# LIFESPAN (Startup/Shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("\n" + "=" * 50)
    print("LLM Query Processor - Vertex AI")
    print("=" * 50)
    try:
        model.generate_content("Hola")
        print("Conexión con Vertex AI establecida")
    except Exception as e:
        print(f"Error al conectar con Vertex AI: {e}\n")
    
    yield
    
    # Shutdown
    print("\nLLM Query Processor - Apagando")

app = FastAPI(
    title="LLM Query Processor - Gemini",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        raise HTTPException(status_code=500, detail=f"Error calling Vertex AI: {error_str}")

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

@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-query-processor"}

@app.post("/analyze")
async def analyze(request: QueryRequest):
    return analyze_query(request.query)

@app.post("/correct")
async def correct(request: QueryRequest):
    return correct_query(request.query)

@app.post("/process")
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=False)
