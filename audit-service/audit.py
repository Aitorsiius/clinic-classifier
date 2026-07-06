"""
Módulo de Auditoría de Códigos CIE-10

Permite validar lotes de diagnósticos contra códigos CIE-10 asignados,
generando reportes de discrepancias y confianza.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
from enum import Enum
import httpx
import time

if TYPE_CHECKING:
    from main import MedicalSearchEngine


class GatewaySearchEngine:
    """Wrapper para hacer búsquedas a través del API Gateway"""
    
    def __init__(self, gateway_url: str):
        self.gateway_url = gateway_url
    
    def search(self, query: str, top_k: int = 5, use_ai: bool = False) -> List[Dict]:
        """
        Busca en el backend a través del gateway

        Args:
            query: Texto a buscar
            top_k: Número de resultados
            use_ai: Si es True, la búsqueda usa el pipeline de IA (primera fase
                LLM que enriquece la consulta + bi-encoder + cross-encoder).

        Returns:
            Lista de resultados de búsqueda
        """
        try:
            client = httpx.Client(timeout=60 if use_ai else 30)
            response = client.post(
                f"{self.gateway_url}/api/search",
                json={"query": query, "top_k": top_k, "use_ai": use_ai}
            )
            client.close()
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                return results
            else:
                return []
        except Exception:
            return []


class DiscrepancyType(str, Enum):
    """Tipos de discrepancias detectadas - Simplificado a 3 tipos"""
    CORRECT = "coincidencia"           # Código es exacta coincidencia
    PARTIAL_MATCH = "parcialmente"     # Código coincide hasta el primer punto o similar
    MISMATCH = "no_coincidencia"       # Código no relacionado


@dataclass
class DiagnosisRecord:
    """Registro individual de diagnóstico a auditar"""
    diagnosis_text: str
    assigned_code: str
    patient_id: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    comorbidities: Optional[List[str]] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class AuditFinding:
    """Hallazgo individual de auditoría"""
    patient_id: str
    diagnosis_text: str
    assigned_code: str
    suggested_code: str
    discrepancy_type: DiscrepancyType
    confidence_score: float           # 0-1: confianza en sugerencia
    match_score: float                # 0-1: similitud con código asignado
    explanation: str
    alternative_codes: List[str]      # Otros códigos posibles
    
    def to_dict(self):
        return {
            **asdict(self),
            "discrepancy_type": self.discrepancy_type.value
        }


@dataclass
class AuditReport:
    """Reporte agregado de auditoría - con 3 tipos simplificados"""
    audit_id: str
    timestamp: datetime
    total_records: int
    total_correct: int          # Coincidencia exacta o parcial con categoría principal
    total_partial_match: int    # Parcialmente - en resultados pero categoría diferente
    total_mismatch: int         # No coincidencia - no encontrado
    
    conformity_percentage: float      # % códigos correctos
    findings: List[AuditFinding]
    # Tiempo total (ms) que tardó el lote completo de auditoría. Se calcula en
    # audit_batch y se propaga a la respuesta y al log para ambos modos (con y
    # sin IA).
    total_time_ms: float = 0.0
    
    def to_dict(self):
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp.isoformat(),
            "total_records": self.total_records,
            "total_correct": self.total_correct,
            "total_partial_match": self.total_partial_match,
            "total_mismatch": self.total_mismatch,
            "conformity_percentage": round(self.conformity_percentage, 2),
            "total_time_ms": round(self.total_time_ms, 2),
            "findings": [f.to_dict() for f in self.findings]
        }


class CodeAuditor:
    """
    Auditor de códigos CIE-10
    
    Utiliza el MedicalSearchEngine para validar códigos asignados
    contra los códigos sugeridos por búsqueda semántica.
    """
    
    def __init__(self, search_engine):
        """
        Inicializa el auditor
        
        Args:
            search_engine: Motor de búsqueda (GatewaySearchEngine o MedicalSearchEngine)
        """
        self.search_engine = search_engine
        self.audit_history: Dict[str, AuditReport] = {}
    
    def audit_record(self, record: DiagnosisRecord, top_k: int = 5, use_ai: bool = False) -> AuditFinding:
        """
        Audita un registro individual de diagnóstico

        Args:
            record: Registro de diagnóstico a auditar
            top_k: Número de resultados a considerar
            use_ai: Si es True, la búsqueda usa el pipeline de IA.

        Returns:
            AuditFinding con el resultado de auditoría
        """
        # 1. Realizar búsqueda del diagnóstico
        search_results = self.search_engine.search(record.diagnosis_text, top_k=top_k, use_ai=use_ai)
        
        if not search_results:
            # No se encontraron resultados - se considera como no coincidencia
            return AuditFinding(
                patient_id=record.patient_id,
                diagnosis_text=record.diagnosis_text,
                assigned_code=record.assigned_code,
                suggested_code="",
                discrepancy_type=DiscrepancyType.MISMATCH,
                confidence_score=0.0,
                match_score=0.0,
                explanation="No se encontraron diagnósticos relacionados en la base de datos",
                alternative_codes=[]
            )
        
        # 2. Analizar coincidencias
        best_match = search_results[0]
        best_code = best_match["payload"]["id"]
        best_score = best_match["score"]
        
        # Extraer códigos alternativos (todos excepto el primero que es el sugerido)
        alternative_codes = [r["payload"]["id"] for r in search_results[1:]]
        
        # 3. Comparar código asignado con el sugerido
        discrepancy_type, match_score, explanation = self._compare_codes(
            record.assigned_code, 
            best_code,
            search_results
        )
        
        return AuditFinding(
            patient_id=record.patient_id,
            diagnosis_text=record.diagnosis_text,
            assigned_code=record.assigned_code,
            suggested_code=best_code,
            discrepancy_type=discrepancy_type,
            confidence_score=best_score,
            match_score=match_score,
            explanation=explanation,
            alternative_codes=alternative_codes
        )
    
    def _compare_codes(
        self, 
        assigned_code: str, 
        suggested_code: str,
        search_results: List[Dict]
    ) -> Tuple[DiscrepancyType, float, str]:
        """
        Compara código asignado con sugerido - Lógica simplificada a 3 tipos
        
        Tipos:
        1. CORRECT (coincidencia): Código exacto o coincide hasta el primer punto
        2. PARTIAL_MATCH (parcialmente): Código está en resultados pero no es exacto/parcial
        3. MISMATCH (no_coincidencia): Código no está en resultados o no relacionado
        
        Incluye lógica especial: Si el código esperado está en la posición esperada
        y todos los anteriores comparten la misma puntuación (1 decimal), se considera
        como CORRECT.
        
        Args:
            assigned_code: Código asignado por codificador
            suggested_code: Código sugerido por búsqueda
            search_results: Resultados de búsqueda
            
        Returns:
            Tuple de (tipo_discrepancia, match_score, explicación)
        """
        # 1. Coincidencia exacta
        if assigned_code == suggested_code:
            return (
                DiscrepancyType.CORRECT,
                1.0,
                "Coincidencia exacta con el resultado de búsqueda."
            )
        
        # 2. Verifica si el código asignado está en los resultados de búsqueda
        assigned_found = False
        assigned_score = 0.0
        assigned_position = -1
        
        for idx, result in enumerate(search_results):
            if result["payload"]["id"] == assigned_code:
                assigned_found = True
                assigned_score = result["score"]
                assigned_position = idx
                break
        
        # 3. LÓGICA ESPECIAL (prioridad): Si el código está en la posición esperada y todos 
        #    los anteriores tienen la misma puntuación (1 decimal), es CORRECT
        if assigned_found and assigned_position > 0:
            all_previous_same_score = self._check_previous_results_same_score(
                search_results, assigned_position, assigned_score
            )
            
            if all_previous_same_score:
                # El código asignado está en la posición correcta con los mismos scores
                previous_codes = [r["payload"]["id"] for r in search_results[:assigned_position]]
                return (
                    DiscrepancyType.CORRECT,
                    assigned_score,
                    f"Coincidencia correcta: el código está en la posición esperada. "
                    f"Los códigos anteriores ({', '.join(previous_codes)}) comparten la misma puntuación ({assigned_score:.1f})."
                )
        
        # 4. Extraer la parte principal (hasta el primer punto) de ambos códigos
        assigned_main = assigned_code.split(".")[0] if assigned_code else ""
        suggested_main = suggested_code.split(".")[0] if suggested_code else ""
        
        # 5. Si la parte principal coincide, es parcialmente
        if assigned_main and suggested_main and assigned_main == suggested_main:
            return (
                DiscrepancyType.PARTIAL_MATCH,
                0.7,  # Score intermedio para coincidencia parcial
                f"Coincidencia parcial: ambos códigos comparten la categoría principal ({assigned_main})"
            )
        
        # 6. Si el código fue encontrado pero no coincide con ninguna regla anterior
        if assigned_found:
            # El código existe en los resultados pero no es exacto ni parcial
            # Esto significa que es un código válido pero diferente
            return (
                DiscrepancyType.PARTIAL_MATCH,
                assigned_score,
                "Código válido pero categoría diferente."
            )
        else:
            # El código no se encontró en los resultados - no coincidencia
            return (
                DiscrepancyType.MISMATCH,
                0.0,
                "Código no encontrado o no relacionado con el diagnóstico."
            )
    
    def _check_previous_results_same_score(
        self,
        search_results: List[Dict],
        position: int,
        target_score: float
    ) -> bool:
        """
        Verifica si todos los resultados anteriores a una posición tienen 
        la misma puntuación (comparación con 1 decimal).
        
        Args:
            search_results: Lista de resultados de búsqueda
            position: Posición a verificar
            target_score: Puntuación objetivo (con 1 decimal)
            
        Returns:
            True si todos los anteriores tienen la misma puntuación, False en caso contrario
        """
        if position <= 0:
            return False
        
        # Redondear a 1 decimal para comparación
        target_rounded = round(target_score, 1)
        
        # Verificar todos los resultados anteriores
        for idx in range(position):
            result_score = round(search_results[idx]["score"], 1)
            if result_score != target_rounded:
                return False
        
        return True
    
    def audit_batch(self, records: List[DiagnosisRecord], top_k: int = 5, progress_callback=None, use_ai: bool = False, should_stop=None) -> AuditReport:
        """
        Audita un lote de registros de diagnósticos

        Args:
            records: Lista de registros a auditar
            top_k: Número de resultados a considerar por búsqueda
            progress_callback: Función callback(current, total) para reportar progreso
            use_ai: Si es True, cada búsqueda usa el pipeline de IA.
            should_stop: Callable opcional que devuelve True cuando se debe abortar
                la auditoría (p. ej. el cliente canceló). Se comprueba antes de
                procesar cada registro para detener el hilo cuanto antes y liberar
                recursos; el informe parcial resultante se descarta.

        Returns:
            AuditReport con hallazgos agregados
        """
        audit_id = f"reporte-auditoria_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        findings: List[AuditFinding] = []

        # Cronómetro del lote completo (incluye, en modo IA, el enriquecimiento
        # por registro). Se reporta en la respuesta y se persiste en el log.
        audit_start = time.perf_counter()

        # Procesar cada registro
        for idx, record in enumerate(records):
            # Parada cooperativa: si el cliente canceló, dejamos de procesar. El
            # informe parcial no se envía (la conexión ya está cerrada).
            if should_stop is not None and should_stop():
                break

            finding = self.audit_record(record, top_k=top_k, use_ai=use_ai)
            findings.append(finding)

            # Pequeño delay para simular procesamiento realista (50-100ms por registro)
            time.sleep(0.05)

            # Llamar callback de progreso si existe
            if progress_callback:
                progress_callback(idx + 1, len(records))
        
        # Calcular estadísticas - Solo 3 tipos
        counts = {
            DiscrepancyType.CORRECT: sum(1 for f in findings if f.discrepancy_type == DiscrepancyType.CORRECT),
            DiscrepancyType.PARTIAL_MATCH: sum(1 for f in findings if f.discrepancy_type == DiscrepancyType.PARTIAL_MATCH),
            DiscrepancyType.MISMATCH: sum(1 for f in findings if f.discrepancy_type == DiscrepancyType.MISMATCH),
        }
        
        # Calcular conformidad: coincidencias completas + (coincidencias parciales × 0.5)
        total_correct = counts[DiscrepancyType.CORRECT]
        total_partial = counts[DiscrepancyType.PARTIAL_MATCH]
        weighted_correct = total_correct + (total_partial * 0.5)
        conformity_percentage = (weighted_correct / len(records) * 100) if records else 0

        # Tiempo total del lote (ms)
        total_time_ms = (time.perf_counter() - audit_start) * 1000

        report = AuditReport(
            audit_id=audit_id,
            timestamp=datetime.now(),
            total_records=len(records),
            total_correct=counts[DiscrepancyType.CORRECT],
            total_partial_match=counts[DiscrepancyType.PARTIAL_MATCH],
            total_mismatch=counts[DiscrepancyType.MISMATCH],
            conformity_percentage=conformity_percentage,
            findings=findings,
            total_time_ms=total_time_ms
        )
        
        # Guardar en historial
        self.audit_history[audit_id] = report
        
        return report
