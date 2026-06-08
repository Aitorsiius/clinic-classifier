import os
import requests
import time
import math
from qdrant_client import QdrantClient

# ==========================================
# CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuración de servicios Docker
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://localhost:8002/embed")
RERANKER_URL = os.getenv("RERANKER_URL", "http://localhost:8001/rerank")

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

        # --- PASO 1: RECUPERACIÓN (Retrieval) ---
        # E5 necesita el prefijo 'query: '
        query_text = f"query: {retrieval_text}"

        # Llamamos al servicio de embeddings para obtener el vector
        query_vector = self._get_vector_from_docker(query_text)

        # Pedimos más candidatos de los necesarios para tener margen en el re-ranking
        search_limit = max(20, top_k * 2) if top_k else 20
        
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
        # Para el Cross-Encoder, limpiamos el prefijo 'passage: '
        documents = [hit.payload['search_text'].replace("passage: ", "") for hit in hits]

        # --- PASO 3: RE-RANKING ---
        # Llamar al servicio de reranker
        # Formato esperado: [[query, doc1], [query, doc2], ...]
        # En modo IA usamos el MISMO texto enriquecido que en la recuperación, de
        # forma que el cross-encoder compara terminología técnica frente al
        # 'search_text' técnico.
        pairs = [[retrieval_text, doc] for doc in documents]
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
            
            reranked_results.append({
                "score": final_score,           # Score híbrido normalizado 0-1
                "original_score": vector_score, # Score original del vector
                "payload": hit.payload
            })

        # Ordenamos por el nuevo score descendente
        reranked_results = sorted(reranked_results, key=lambda x: x['score'], reverse=True)

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