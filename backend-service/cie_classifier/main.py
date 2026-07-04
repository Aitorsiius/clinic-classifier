import os
import re
import time
import math
import unicodedata
import requests
from qdrant_client import QdrantClient

# ==========================================
# CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# NEUTRALIZACIÓN DE TÉRMINOS COMODÍN CIE-10
# ==========================================
# La CIE-10-ES usa "coletillas" estructurales y vacías de contenido clínico para
# nombrar las variantes residuales de un código (p. ej. "Insuficiencia cardiaca,
# no especificada"). Estos términos comodín aparecen en MUCHÍSIMOS títulos del
# catálogo, así que cuando la consulta también los contiene el motor vectorial
# empareja por la coincidencia del comodín y no por la enfermedad: provoca un
# "colapso semántico" en el que códigos inconexos (cardiacos, p. ej.) empatan con
# alta confianza frente a un cuadro infeccioso. Para evitarlo, los eliminamos del
# texto ANTES de la similitud del coseno y del re-ranking, en ambos lados de la
# comparación, de modo que solo pese el contenido clínico real.
#
# IMPORTANTE: NO se neutraliza "sin complicaciones", que SÍ es un eje
# discriminante real (variante base frente a variante con complicaciones) y que el
# prompt del LLM usa de forma deliberada.
_WILDCARD_PATTERNS = [
    r"no\s+especificad[oa]s?(?:\s+de\s+otra\s+(?:manera|forma))?",
    r"sin\s+especificar",
    r"sin\s+(?:otra\s+)?especificaci[oó]n",
    r"sin\s+otra\s+indicaci[oó]n",
    r"no\s+clasificad[oa]s?\s+en\s+otra\s+parte",
    r"no\s+clasificad[oa]s?\s+bajo\s+otros?\s+conceptos?",
    r"\bSAI\b",
    r"\bNCOP\b",
    r"\bNEOM\b",
]
_WILDCARD_REGEX = re.compile("|".join(_WILDCARD_PATTERNS), flags=re.IGNORECASE)
# Limpieza de puntuación/espacios que quedan colgando tras eliminar la coletilla.
_DANGLING_PUNCT_REGEX = re.compile(r"\s*([,;:])(?=\s*[,;:])")
_TRAILING_PUNCT_REGEX = re.compile(r"[\s,;:.\-]+$")
_LEADING_PUNCT_REGEX = re.compile(r"^[\s,;:.\-]+")
_MULTISPACE_REGEX = re.compile(r"\s{2,}")


def neutralize_wildcard_terms(text: str) -> str:
    """Elimina los términos comodín de la CIE-10 de un texto.

    Se aplica a la consulta y a los documentos del catálogo en la fase de
    similitud (bi-encoder) y de re-ranking (cross-encoder) para que el comodín
    "no especificado/a" deje de actuar como puente de emparejamiento entre textos
    clínicamente inconexos. Devuelve el texto sin comodines, con la puntuación y
    los espacios sobrantes saneados. Si el texto quedara vacío (caso límite en el
    que el usuario solo escribió comodines), el llamante debe conservar el
    original para no enviar una cadena vacía al embedding.
    """
    if not text:
        return text
    cleaned = _WILDCARD_REGEX.sub(" ", text)
    cleaned = _MULTISPACE_REGEX.sub(" ", cleaned)
    cleaned = _DANGLING_PUNCT_REGEX.sub("", cleaned)
    cleaned = _LEADING_PUNCT_REGEX.sub("", cleaned)
    cleaned = _TRAILING_PUNCT_REGEX.sub("", cleaned)
    return cleaned.strip()


# ==========================================
# DESEMPATE POR EJES CRÍTICOS (LATERALIDAD Y LOCALIZACIÓN)
# ==========================================
# El bi-encoder (y, en menor medida, el cross-encoder) sufren un "efecto de
# dilución": las descripciones CIE-10 son largas y redundantes, así que el peso
# matemático recae en el texto general de la enfermedad y se diluyen los detalles
# que de verdad distinguen un código de otro: la LATERALIDAD ("ambas manos" vs
# "mano izquierda") y la LOCALIZACIÓN anatómica ("mano" vs "hombro"). El re-ranker
# acierta el bloque (p. ej. M05, Artritis Reumatoide) pero deja empatadas
# variantes clínicamente contradictorias.
#
# Esta capa actúa DESPUÉS del cross-encoder y reordena esos empates aplicando un
# ajuste determinista sobre los dos ejes: bonifica cuando la consulta y el
# candidato COINCIDEN en el eje y penaliza cuando se CONTRADICEN. No sustituye al
# cross-encoder: lo complementa allí donde la atención cruzada no basta para
# separar candidatos casi idénticos salvo por estos ejes.

# Magnitudes pensadas para romper empates en el rango habitual de scores (~0.7-0.9)
# sin invertir el orden cuando el cross-encoder ya separa con claridad.
_AXIS_MATCH_BONUS = 0.05
_AXIS_CONTRADICTION_PENALTY = 0.15

_LATERALITY_PATTERNS = {
    "right": re.compile(r"\bderech[oa]s?\b", re.IGNORECASE),
    "left": re.compile(r"\bizquierd[oa]s?\b", re.IGNORECASE),
}
_BILATERAL_REGEX = re.compile(
    r"\bbilateral(?:es)?\b|\bamb[oa]s\b|\blos\s+dos\b|\blas\s+dos\b", re.IGNORECASE
)

# Localizaciones anatómicas relevantes para el desempate (articulaciones y
# regiones frecuentes). Cada clave agrupa sus variantes morfológicas.
_ANATOMICAL_SITES = {
    "mano": re.compile(r"\bmanos?\b", re.IGNORECASE),
    "muñeca": re.compile(r"\bmu[ñn]ecas?\b|\bcarpo\b", re.IGNORECASE),
    "codo": re.compile(r"\bcodos?\b", re.IGNORECASE),
    "hombro": re.compile(r"\bhombros?\b", re.IGNORECASE),
    "brazo": re.compile(r"\b(?:ante)?brazos?\b", re.IGNORECASE),
    "rodilla": re.compile(r"\brodillas?\b", re.IGNORECASE),
    "cadera": re.compile(r"\bcaderas?\b", re.IGNORECASE),
    "tobillo": re.compile(r"\btobillos?\b", re.IGNORECASE),
    "pie": re.compile(r"\bpies?\b", re.IGNORECASE),
    "columna": re.compile(r"\bcolumna\b|\bvertebr\w*\b|\bcervical\w*\b|\blumbar\w*\b", re.IGNORECASE),
}


def detect_laterality(text: str) -> set:
    """Devuelve la lateralidad expresada en el texto: {"right"}, {"left"} o
    {"bilateral"}, o un conjunto vacío si no se menciona.

    "ambas manos", "bilateral" o mencionar a la vez derecho e izquierdo se
    normalizan a {"bilateral"}, porque clínicamente un código de un solo lado
    contradice un cuadro bilateral.
    """
    if not text:
        return set()
    found = set()
    if _BILATERAL_REGEX.search(text):
        found.add("bilateral")
    for side, pattern in _LATERALITY_PATTERNS.items():
        if pattern.search(text):
            found.add(side)
    if "bilateral" in found or {"right", "left"} <= found:
        return {"bilateral"}
    return found


def detect_anatomical_sites(text: str) -> set:
    """Devuelve el conjunto de localizaciones anatómicas presentes en el texto."""
    if not text:
        return set()
    return {site for site, pattern in _ANATOMICAL_SITES.items() if pattern.search(text)}


def axis_match_adjustment(query_text: str, doc_text: str) -> float:
    """Calcula el ajuste de score por coincidencia/contradicción en los ejes de
    desempate (lateralidad y localización anatómica).

    Por cada eje en el que AMBOS textos aportan información:
    - bonifica si coinciden (`+_AXIS_MATCH_BONUS`),
    - penaliza si se contradicen (`-_AXIS_CONTRADICTION_PENALTY`).
    Si alguno de los dos no menciona el eje, este es neutro (0): no penalizamos a
    los códigos genéricos ni a las patologías sin lateralidad.
    """
    adjustment = 0.0

    q_lat, d_lat = detect_laterality(query_text), detect_laterality(doc_text)
    if q_lat and d_lat:
        adjustment += _AXIS_MATCH_BONUS if q_lat == d_lat else -_AXIS_CONTRADICTION_PENALTY

    q_site, d_site = detect_anatomical_sites(query_text), detect_anatomical_sites(doc_text)
    if q_site and d_site:
        adjustment += _AXIS_MATCH_BONUS if (q_site & d_site) else -_AXIS_CONTRADICTION_PENALTY

    return adjustment


# ==========================================
# DEFECTO CONSERVADOR ANTE EMPATE TÉCNICO
# ==========================================
# Norma de codificación CIE-10-ES: cuando el paciente no aporta el eje que separa
# las variantes de una misma patología (gravedad, lateralidad, tipo…), debe
# asignarse la variante RESIDUAL "no especificada" (que estructuralmente suele
# terminar en el dígito genérico .9), nunca una variante grave o lateralizada que
# el clínico no ha confirmado.
#
# El motor vectorial, ante esa falta de datos, deja un EMPATE TÉCNICO: varios
# códigos de la misma patología con confianza casi idéntica. Esta capa final
# detecta ese empate y promueve a la primera posición la variante conservadora.
# Solo actúa dentro de una MISMA patología (misma categoría CIE-10) y solo cuando
# el margen es estrecho: si el motor ha separado los códigos con holgura (porque
# el paciente SÍ dio el dato), no interfiere.

# Margen por debajo del cual dos códigos se consideran en empate técnico.
TIE_MARGIN = 0.05
# Solapamiento léxico mínimo (Jaccard) entre la enriched_query y la descripción de
# un código genérico para considerar que hablan de la MISMA patología.
LEXICAL_MATCH_THRESHOLD = 0.2

# Palabras vacías y estructurales que se ignoran al medir la coincidencia léxica:
# artículos/preposiciones, los comodines CIE-10 y los sustantivos genéricos de
# cabecera ("síndrome", "enfermedad", "trastorno") que NO discriminan la patología.
_LEXICAL_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "u",
    "en", "con", "sin", "por", "para", "al", "su", "sus", "que", "no", "es", "se",
    "especificada", "especificado", "especificadas", "especificados", "especificar",
    "especificacion", "complicacion", "complicaciones", "mencion", "otra", "otras",
    "otro", "otros", "parte", "concepto", "conceptos",
    "sindrome", "enfermedad", "enfermedades", "trastorno", "trastornos",
}


def _fold(text: str) -> str:
    """Normaliza un texto a minúsculas, sin acentos y sin puntuación, CONSERVANDO el
    orden de las palabras (necesario para localizar construcciones como 'con X')."""
    folded = unicodedata.normalize("NFKD", str(text or "").lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", folded)


def _content_tokens(text: str) -> set:
    """Tokens de contenido de un texto: minúsculas, sin acentos, sin puntuación, sin
    palabras vacías ni comodines y con longitud >= 3. Son las palabras que de verdad
    nombran la enfermedad."""
    if not text:
        return set()
    return {w for w in _fold(text).split() if len(w) >= 3 and w not in _LEXICAL_STOPWORDS}


def complication_status(title: str, query_text: str) -> int:
    """Clasifica una variante genérica según la complicación que añade con "con X":

    - ``+1`` si el título añade una complicación ("con hematuria", "con hemorragia"…)
      que la consulta SÍ menciona explícitamente -> es la variante pedida.
    - ``-1`` si añade una complicación que la consulta NO menciona -> no debe asignarse
      por defecto (sería una alucinación clínica).
    -  ``0`` si NO añade complicación con "con" (variante "sin"/base, segura por defecto).

    Solo mira el primer término significativo tras cada "con", que es la cabeza de la
    complicación en los títulos CIE-10 ("…con hematuria", "…con hemorragia").
    """
    comp_terms = set()
    for m in re.finditer(r"\bcon\b((?:\s+\w+){1,4})", _fold(title)):
        for tok in m.group(1).split():
            if len(tok) >= 3 and tok not in _LEXICAL_STOPWORDS:
                comp_terms.add(tok)
                break  # solo la cabeza de la complicación tras este "con"
    if not comp_terms:
        return 0
    return 1 if (comp_terms & _content_tokens(query_text)) else -1


def lexical_overlap(query_text: str, doc_text: str) -> float:
    """Coeficiente de solapamiento DIRIGIDO: porcentaje de los tokens de contenido de
    la CONSULTA que también aparecen en la descripción del código (``|q ∩ d| / |q|``).

    A diferencia de Jaccard, NO penaliza al título por ser más largo, sino que premia
    cubrir más MODIFICADORES de la consulta. Así, ante "Anemia ferropénica", el código
    "Anemia ferropénica, no especificada" (cubre 'anemia' y 'ferropénica' -> 1.0) gana
    a "Anemia, no especificada" (cubre solo 'anemia' -> 0.5), evitando el "secuestro de
    jerarquía" hacia el genérico absoluto. Devuelve 0.0 si alguno no aporta tokens.
    """
    q = _content_tokens(query_text)
    d = _content_tokens(doc_text)
    if not q or not d:
        return 0.0
    return len(q & d) / len(q)


def is_unspecified_variant(payload) -> bool:
    """Indica si un resultado es la variante RESIDUAL/conservadora de su patología.

    Se considera residual si su título contiene "no especificad@" o si su código
    termina en el dígito genérico 9 (p. ej. I50.9, M05.049, J45.909). Se EXCLUYEN
    los títulos "otros/otras …", que son una variante *especificada distinta* (no
    el cajón residual) aunque su código pueda acabar en 8/9.
    """
    if not isinstance(payload, dict):
        return False
    title = str(payload.get("title", "")).lower()
    code = str(payload.get("id", "")).strip()
    if "otros" in title or "otras" in title:
        return False
    if "no especificad" in title:
        return True
    return code.endswith("9")


# Etiología NO declarada: en CIE-10-ES la opción por defecto es la forma "primaria"/
# "esencial" (p. ej. "Hipertensión esencial (primaria)" I10), frente a las variantes
# "secundaria" a una causa concreta. Se usa como alternativa conservadora cuando en el
# empate NO hay ninguna variante "no especificada"/.9.
_PRIMARY_DEFAULT_REGEX = re.compile(r"\b(?:primari[oa]s?|esencial(?:es)?)\b", re.IGNORECASE)


def is_primary_default_variant(payload) -> bool:
    """Indica si un resultado es la variante por defecto para etiología no declarada:
    la descrita como "primaria/primario" o "esencial". Excluye los títulos "otros/otras"
    (variante especificada distinta)."""
    if not isinstance(payload, dict):
        return False
    title = str(payload.get("title", "")).lower()
    if "otros" in title or "otras" in title:
        return False
    return bool(_PRIMARY_DEFAULT_REGEX.search(title))


def promote_conservative_default(results, query_text: str, margin: float = TIE_MARGIN):
    """Promueve a la primera posición la variante conservadora ante un empate, bajo
    DOBLE VALIDACIÓN para no promover falsos positivos.

    1) Filtra del bloque en empate técnico (margen < ``margin`` con el primero) solo
       los códigos GENÉRICOS (``is_unspecified_variant``: terminados en .9 o con la
       etiqueta "no especificad@").
    2) Para cada genérico cruza la ``query_text`` (la enriched_query del LLM) con su
       descripción mediante ``lexical_overlap`` (% de modificadores de la consulta
       cubiertos) y elige el de MAYOR cobertura que supere ``LEXICAL_MATCH_THRESHOLD``.
       A igualdad de cobertura, prefiere el genérico MÁS general (menos tokens), para
       no arrastrar modificadores que el usuario no pidió. Así se evita el "secuestro
       de jerarquía" (promover "Anemia, no especificada" cuando la consulta dice
       "ferropénica" y existe "Anemia ferropénica, no especificada") y se descartan
       genéricos INTRUSOS de otra patología (p. ej. paratiroides buscando tiroides).
    3) Exclusión de complicaciones (``complication_status``): si entre las variantes
       genéricas hay un par "con X" / "sin X" (p. ej. "Cistitis, no especificada, con
       hematuria" vs "…sin hematuria"), DESCARTA la variante "con X" salvo que la
       consulta mencione X explícitamente, y deja por defecto la variante "sin X" para
       no inventar una complicación grave que el paciente no tiene.

    Se evalúan TODOS los candidatos del empate, incluido el que ocupe ya el Top 1: si
    hay uno más específico empatado por debajo, sube. Al promover se iguala el score del
    elegido al máximo del empate para que la confianza sea coherente. No modifica nada
    si no hay empate, si no hay candidatos válidos o si ninguno supera el umbral.

    4) Si en el empate NO existe ninguna variante "no especificada"/.9, se recurre a la
       opción por defecto para etiología no declarada: la variante "primaria/esencial"
       (``is_primary_default_variant``), p. ej. "Hipertensión esencial (primaria)".
    """
    if len(results) < 2:
        return results

    top_score = results[0]["score"]
    # Empate técnico con el primero (incluye al propio primero).
    tied = [r for r in results if top_score - r["score"] < margin]
    if len(tied) < 2:
        return results

    # Regla 1: del empate, los códigos genéricos ("no especificada"/.9). Si no hay
    # ninguno, se recurre a la variante por defecto "primaria/esencial" (Regla 4).
    candidates = [r for r in tied if is_unspecified_variant(r["payload"])]
    if not candidates:
        candidates = [r for r in tied if is_primary_default_variant(r["payload"])]
    if not candidates:
        return results

    # Regla 2 y 3: validación léxica + exclusión de complicaciones. Para cada candidato:
    #   - Si añade una complicación "con X" que la consulta NO pide, se DESCARTA: nunca
    #     se asigna por defecto una complicación inventada (p. ej. "con hematuria").
    #   - El resto se ordena por (cobertura de modificadores, complicación pedida,
    #     generalidad): premia el código específico correcto y, ante "con/sin"
    #     equivalentes, prefiere "sin" salvo que la consulta pida la complicación.
    best, best_key = None, (-1.0, -1, 0)
    for r in candidates:
        payload = r["payload"]
        title = payload.get("title", "") if isinstance(payload, dict) else ""
        status = complication_status(title, query_text)
        if status < 0:
            continue  # complicación no solicitada: no se promueve por defecto
        sim = lexical_overlap(query_text, title)
        key = (sim, status, -len(_content_tokens(title)))
        if key > best_key:
            best, best_key = r, key

    if best is None or best_key[0] < LEXICAL_MATCH_THRESHOLD:
        return results

    # Si el mejor candidato ya está en el Top 1, no hay nada que mover.
    if results[0] is best:
        return results

    results.remove(best)
    best["score"] = top_score  # confianza coherente con su nueva posición
    results.insert(0, best)
    return results

# Configuración de servicios Docker
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://localhost:8002/embed")
RERANKER_URL = os.getenv("RERANKER_URL", "http://localhost:8001/rerank")

# Nº de candidatos que el bi-encoder recupera de Qdrant y entrega al cross-encoder
# para re-rankear. Es el "embudo" del pipeline: cuanto mayor sea, más probable que
# el código correcto entre en el pool y el re-ranker pueda rescatarlo, a costa de algo
# más de latencia en el cross-encoder. Debe ser cómodamente mayor que el top_k máximo
# (20 en el front) para que el re-ranking aporte valor real. Configurable por entorno.
RETRIEVAL_CANDIDATES = int(os.getenv("RETRIEVAL_CANDIDATES", "80"))

# Rutas base de datos Qdrant
QDRANT_DB_PATH = os.path.join(os.path.dirname(BASE_DIR), "cie10_qdrant")
COLLECTION_NAME = "cie10_qdrant"

class MedicalSearchEngine:
    def __init__(self):
        print("1-4 Inicializando sistema...")
        
        # Verificar el contenedor Docker de Embeddings
        print(f"2-4 Conectando con Modelo de Embeddings: {EMBEDDING_URL}")
        max_retries = 5
        retry_delay = 2
        for attempt in range(max_retries):
            try:
                # Llamada de prueba
                response = requests.post(EMBEDDING_URL, json={"inputs": "test connection"}, timeout=5)
                if response.status_code == 200:
                    print("Conexión con servicio de embeddings establecida.")
                    break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    print(f"  Intento {attempt + 1}/{max_retries} falló, reintentando en {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"\nERROR: No se puede conectar al servicio de embeddings en {EMBEDDING_URL}")
                    raise ConnectionError("Embedding service is down")

        # Verificar el servicio de Reranker
        print(f"3-4 Conectando con servicio de Reranker: {RERANKER_URL}")
        max_retries = 15
        retry_delay = 3
        health_url = RERANKER_URL.rsplit('/', 1)[0] + '/health'
        for attempt in range(max_retries):
            try:
                response = requests.get(health_url, timeout=10)
                if response.status_code == 200:
                    print("Conexión con servicio de reranker establecida.")
                    break
                else:
                    print(f"  Intento {attempt + 1}/{max_retries}: Reranker respondió con status {response.status_code}")
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries - 1:
                    print(f"  Intento {attempt + 1}/{max_retries} falló ({type(e).__name__}), reintentando en {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"\nERROR: No se puede conectar al servicio de reranker en {health_url}")
                    print(f"  Último error: {type(e).__name__}: {str(e)}")
                    raise ConnectionError("Reranker service is down")

        # Conectar a Qdrant
        print(f"4-4 Conectando a base de datos Qdrant: {QDRANT_DB_PATH}")
        self.client = QdrantClient(path=QDRANT_DB_PATH)
        
        # Verificar conexión con Qdrant
        try:
            self.client.get_collection(COLLECTION_NAME)
        except Exception:
            raise ValueError(f"\nERROR: La colección '{COLLECTION_NAME}' no existe.")
            
        print("\n\n-- Sistema listo para diagnósticos. --")

    def _get_vector_from_docker(self, text: str):
        """Función auxiliar para pedir el vector al contenedor"""
        payload = {"inputs": text}
        response = requests.post(EMBEDDING_URL, json=payload)
        
        if response.status_code == 200:
            # La respuesta contiene una lista de vectores
            return response.json()[0]
        else:
            raise Exception(f"ERROR (en Docker): {response.text}")

    def _looks_like_code(self, query: str) -> bool:
        """
        Detectar si la query parece un código CIE-10
        Formatos reconocidos: A00.0, A00, I40.1, etc.
        """
        import re
        # Patrón: letra(s) seguida de números y opcionalmente un punto y más números
        pattern = r'^[A-Z]{1,3}\d{1,2}(?:\.\d{1,3})?$'
        return bool(re.match(pattern, query.strip().upper()))

    def search_by_code_exact(self, code: str, top_k: int = 5):
        """
        Búsqueda EXACTA por código
        """
        try:
            points, _ = self.client.scroll(
                collection_name=COLLECTION_NAME,
                limit=100000
            )
            
            # Buscar coincidencias exactas y parciales
            exact_match = None
            partial_matches = []
            
            for point in points:
                payload = point.payload
                point_code = payload.get('id', '')
                
                if point_code.upper() == code.upper():
                    # Coincidencia exacta
                    exact_match = {
                        "score": 1.0,  # Score máximo para coincidencia exacta
                        "original_score": 1.0,
                        "payload": payload
                    }
                elif code.upper() in point_code.upper():
                    # Coincidencia parcial
                    partial_matches.append({
                        "score": 0.99,  # Score muy alto para coincidencia parcial
                        "original_score": 0.99,
                        "payload": payload
                    })
            
            # Retornar resultados ordenados: exacto primero, luego parciales
            results = []
            if exact_match:
                results.append(exact_match)
            results.extend(partial_matches[:top_k - 1])
            
            return results
            
        except Exception as e:
            print(f"ERROR en búsqueda exacta por código: {e}")
            return []

    def search(self, user_query: str, top_k: int = 5, enriched_query: str = None):
        """
        1. Intenta búsqueda exacta por código
        2. Si no encuentra, llama a Docker para vectorizar
        3. Busca candidatos en Qdrant
        4. Re-ordena (Rerank) con Cross-Encoder

        Args:
            user_query: Consulta original del usuario.
            top_k: Número de resultados a devolver.
            enriched_query: (Opcional) Texto enriquecido por la IA en la primera
                fase del pipeline. Cuando se proporciona, se usa TANTO para la
                recuperación (bi-encoder) COMO para el re-ranking (cross-encoder),
                de modo que ambas fases comparan terminología técnica frente al
                'search_text' técnico de la base. Si es None, el comportamiento es
                idéntico al modo sin IA.
        """
        
        # --- PASO 0: INTENTO DE BÚSQUEDA EXACTA POR CÓDIGO ---
        # Detectar si la query parece un código (ej: "A00.0", "I40.1")
        query_upper = user_query.strip().upper()
        if self._looks_like_code(query_upper):
            exact_results = self.search_by_code_exact(query_upper, top_k=top_k)
            if exact_results:
                print(f"[DIRECT MATCH] Código encontrado directamente: {query_upper}")
                return exact_results

        # Texto que se usará para recuperar y re-rankear. En modo IA es el texto
        # enriquecido; en modo normal es la consulta original del usuario.
        retrieval_text = (enriched_query or "").strip() or user_query

        # Neutralizamos los comodines CIE-10 ("no especificado/a"…) para que la
        # similitud del coseno y el cross-encoder se basen en el contenido clínico
        # y no en la coincidencia de la coletilla estructural. Si la limpieza
        # vaciara el texto (solo había comodines), conservamos el original.
        clean_retrieval_text = neutralize_wildcard_terms(retrieval_text) or retrieval_text

        # --- PASO 1: RECUPERACIÓN (Retrieval) ---
        # E5 necesita el prefijo 'query: '
        query_text = f"query: {clean_retrieval_text}"

        # Llamamos al servicio de embeddings para obtener el vector
        query_vector = self._get_vector_from_docker(query_text)

        # Pedimos muchos más candidatos de los que se devuelven para dar margen al
        # re-ranking: el cross-encoder reordena todo este pool y nos quedamos con top_k.
        search_limit = max(RETRIEVAL_CANDIDATES, top_k * 2) if top_k else RETRIEVAL_CANDIDATES
        
        # Usar query_points para la nueva versión de qdrant-client
        try:
            # Intenta con el nuevo API (qdrant-client >= 1.7.0)
            hits = self.client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                limit=search_limit,
                with_payload=True,
                with_vectors=False
            ).points
        except (AttributeError, TypeError):
            # Fallback al antiguo API
            hits = self.client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=search_limit 
            )

        if not hits:
            return []

        # --- PASO 2: PREPARACIÓN RE-RANKING ---
        # Usamos el 'search_text' que contiene todo el contexto enriquecido
        # Para el Cross-Encoder, limpiamos el prefijo 'passage: ' y neutralizamos
        # los comodines del catálogo (la mayoría de títulos residuales acaban en
        # "no especificada"); así el cross-encoder reordena por la enfermedad y no
        # por la coletilla compartida.
        documents = [
            neutralize_wildcard_terms(hit.payload['search_text'].replace("passage: ", ""))
            for hit in hits
        ]

        # --- PASO 3: RE-RANKING ---
        # Llamar al servicio de reranker
        # Formato esperado: [[query, doc1], [query, doc2], ...]
        # En modo IA usamos el MISMO texto enriquecido (ya sin comodines) que en la
        # recuperación, de forma que el cross-encoder compara terminología técnica
        # frente al 'search_text' técnico, también saneado.
        pairs = [[clean_retrieval_text, doc] for doc in documents]
        rerank_payload = {"inputs": pairs}
        
        try:
            rerank_response = requests.post(RERANKER_URL, json=rerank_payload, timeout=30)
            rerank_response.raise_for_status()
            raw_scores = rerank_response.json()
            if not isinstance(raw_scores, list):
                raw_scores = []
        except Exception as e:
            print(f"ERROR en reranking: {e}")
            raw_scores = []  # Fallback: usaremos solo vector scores

        # Texto del que se extraen los ejes de desempate de la consulta. Se combina
        # la consulta original con la enriquecida para no perder la lateralidad o la
        # localización si el enriquecimiento por IA las hubiera omitido.
        query_axis_text = f"{user_query} {clean_retrieval_text}"

        # Combinamos el resultado de Qdrant con el nuevo score del Reranker
        reranked_results = []
        for idx, hit in enumerate(hits):
            vector_score = hit.score  # Cosine Similarity (~0.7 a 0.9 para relevantes)

            # Obtener score del reranker si está disponible, sino usar simulación basada en vector
            if idx < len(raw_scores):
                logit_score = raw_scores[idx]
                reranker_prob = 1 / (1 + math.exp(-logit_score))  # Sigmoid: logits -> [0, 1]
            else:
                reranker_prob = vector_score  # Fallback si no hay score

            # Estrategia Híbrida Ponderada:
            # - Reranker Score (Cross-Encoder): Muy preciso (85% peso)
            # - Vector Score (Bi-Encoder): Retrieval rápido (15% peso)
            final_score = (reranker_prob * 0.85) + (vector_score * 0.15)

            # Desempate por ejes críticos: rompe los empates que el cross-encoder
            # deja entre variantes contradictorias en lateralidad/localización.
            final_score += axis_match_adjustment(query_axis_text, documents[idx])
            # Mantenemos el score en el rango normalizado [0, 1].
            final_score = max(0.0, min(1.0, final_score))

            reranked_results.append({
                "score": final_score,           # Score híbrido normalizado 0-1
                "original_score": vector_score, # Score original del vector
                "payload": hit.payload
            })

        # Ordenamos por el nuevo score descendente
        reranked_results = sorted(reranked_results, key=lambda x: x['score'], reverse=True)

        # Defecto conservador: ante un empate técnico, promovemos la variante
        # "no especificada"/.9 (norma de codificación CIE-10-ES) SOLO si coincide
        # léxicamente con lo que buscaba el LLM, para no promover genéricos intrusos.
        # Se hace antes de recortar a top_k para poder rescatar la variante residual
        # aunque hubiera quedado algo más abajo en el empate.
        reranked_results = promote_conservative_default(reranked_results, clean_retrieval_text)

        return reranked_results[:top_k]

# ==========================================
# FUNCIÓN PARA MOSTRAR RESULTADOS (Trazabilidad)
# ==========================================
def print_traceability(results):
    if not results:
        print("\nWARN: No se encontraron coincidencias.")
        return

    print(f"\n-- Se encontraron {len(results)} diagnósticos probables --\n")
    
    for i, res in enumerate(results):
        payload = res['payload']
        code = payload['id']
        title = payload['title']
        score = res['score'] 
        
        # Leemos la jerarquía del JSON con los nodos finales
        hierarchy = payload.get('metadata', {}).get('hierarchy', [])
        
        print(f"#{i+1} [Score: {score:.2f}] ==> CÓDIGO: {code}")
        print(f"   1. Diagnóstico: {title}")
        print("   2. Trazabilidad (Ruta CIE-10):")
        
        # Construimos la representación de la jerarquía
        indent = "      "
        for level_idx, step in enumerate(hierarchy):
            connector = "└─ " if level_idx == len(hierarchy) - 1 else "├─ "
            print(f"{indent}{connector}{step['code']} - {step['title']}")
            indent += "│  "
        
        # Imprimimos el nodo final
        print(f"{indent}└─ {code} - {title}")
        print("-" * 60)

# ==========================================
# MAIN LOOP
# ==========================================
if __name__ == "__main__":
    try:
        engine = MedicalSearchEngine()
        
        print("\n> Escribe un diagnóstico médico (o 'salir').")
        
        while True:
            try:
                user_input = input("\n> Diagnóstico: ").strip()
                if user_input.lower() in ['salir', 'exit', 'quit']:
                    break
                if not user_input: continue
                
                # Ejecutamos la búsqueda (en este caso recuperamos el top_k=3 candidatos)
                results = engine.search(user_input, top_k=3)
                
                # Mostramos los resultados
                print_traceability(results)
                
            except KeyboardInterrupt:
                print("\n> Saliendo...")
                break
            except Exception as e:
                print(f"ERROR (en búsqueda): {e}")
                
    except ConnectionError:
        print("ERROR: Deteniendo programa por falta de conexión a Docker.")
    except Exception as e:
        print(f"ERROR: Error al iniciar: {e}")