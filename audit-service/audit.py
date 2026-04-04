"""
Módulo de Auditoría de Códigos CIE-10

Permite validar lotes de diagnósticos contra códigos CIE-10 asignados,
generando reportes de discrepancias y confianza.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
import json
import csv
from enum import Enum
import httpx
import time

if TYPE_CHECKING:
    from main import MedicalSearchEngine


class GatewaySearchEngine:
    """Wrapper para hacer búsquedas a través del API Gateway"""
    
    def __init__(self, gateway_url: str):
        self.gateway_url = gateway_url
    
    def search(self, query: str, top_k: int = 5, algorithm: str = "hybrid") -> List[Dict]:
        """
        Busca en el backend a través del gateway
        
        Args:
            query: Texto a buscar
            top_k: Número de resultados
            algorithm: Algoritmo a usar
            
        Returns:
            Lista de resultados de búsqueda
        """
        try:
            client = httpx.Client(timeout=30)
            response = client.post(
                f"{self.gateway_url}/api/search",
                json={"query": query, "top_k": top_k, "algorithm": algorithm}
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
    
    def to_dict(self):
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp.isoformat(),
            "total_records": self.total_records,
            "total_correct": self.total_correct,
            "total_partial_match": self.total_partial_match,
            "total_mismatch": self.total_mismatch,
            "conformity_percentage": round(self.conformity_percentage, 2),
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
    
    def audit_record(self, record: DiagnosisRecord, top_k: int = 5, algorithm: str = "hybrid") -> AuditFinding:
        """
        Audita un registro individual de diagnóstico
        
        Args:
            record: Registro de diagnóstico a auditar
            top_k: Número de resultados a considerar
            algorithm: Algoritmo de búsqueda a utilizar
            
        Returns:
            AuditFinding con el resultado de auditoría
        """
        # 1. Realizar búsqueda del diagnóstico
        search_results = self.search_engine.search(record.diagnosis_text, top_k=top_k, algorithm=algorithm)
        
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
    
    def audit_batch(self, records: List[DiagnosisRecord], algorithm: str = "algoritmo1", top_k: int = 5, progress_callback=None) -> AuditReport:
        """
        Audita un lote de registros de diagnósticos
        
        Args:
            records: Lista de registros a auditar
            algorithm: Algoritmo de búsqueda a utilizar (algoritmo1, algoritmo2, etc.)
            top_k: Número de resultados a considerar por búsqueda
            progress_callback: Función callback(current, total) para reportar progreso
            
        Returns:
            AuditReport con hallazgos agregados
        """
        audit_id = f"reporte-auditoria-{algorithm}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        findings: List[AuditFinding] = []
        
        # Procesar cada registro
        for idx, record in enumerate(records):
            finding = self.audit_record(record, top_k=top_k, algorithm=algorithm)
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
        
        report = AuditReport(
            audit_id=audit_id,
            timestamp=datetime.now(),
            total_records=len(records),
            total_correct=counts[DiscrepancyType.CORRECT],
            total_partial_match=counts[DiscrepancyType.PARTIAL_MATCH],
            total_mismatch=counts[DiscrepancyType.MISMATCH],
            conformity_percentage=conformity_percentage,
            findings=findings
        )
        
        # Guardar en historial
        self.audit_history[audit_id] = report
        
        return report
    
    def get_summary_statistics(self, report: AuditReport) -> Dict:
        """
        Genera estadísticas de resumen del reporte
        
        Args:
            report: AuditReport para analizar
            
        Returns:
            Dict con estadísticas de resumen
        """
        return {
            "total_audited": report.total_records,
            "conformity_percentage": report.conformity_percentage,
            "breakdown": {
                "correct": {
                    "count": report.total_correct,
                    "percentage": round(report.total_correct / report.total_records * 100, 2) if report.total_records else 0
                },
                "partial_match": {
                    "count": report.total_partial_match,
                    "percentage": round(report.total_partial_match / report.total_records * 100, 2) if report.total_records else 0
                },
                "alternative": {
                    "count": report.total_alternative,
                    "percentage": round(report.total_alternative / report.total_records * 100, 2) if report.total_records else 0
                },
                "mismatch": {
                    "count": report.total_mismatch,
                    "percentage": round(report.total_mismatch / report.total_records * 100, 2) if report.total_records else 0
                },
                "not_found": {
                    "count": report.total_not_found,
                    "percentage": round(report.total_not_found / report.total_records * 100, 2) if report.total_records else 0
                }
            },
            "critical_issues": {
                "mismatch_count": report.total_mismatch,
                "not_found_count": report.total_not_found
            }
        }
    
    def export_to_json(self, report: AuditReport, filepath: str):
        """
        Exporta reporte a JSON
        
        Args:
            report: AuditReport a exportar
            filepath: Ruta del archivo destino
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    
    def export_to_csv(self, report: AuditReport, filepath: str):
        """
        Exporta hallazgos a CSV
        
        Args:
            report: AuditReport a exportar
            filepath: Ruta del archivo destino
        """
        if not report.findings:
            return
        
        fieldnames = [
            'patient_id', 'diagnosis_text', 'assigned_code', 
            'suggested_code', 'discrepancy_type', 'confidence_score',
            'match_score', 'explanation', 'alternative_codes'
        ]
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for finding in report.findings:
                row = finding.to_dict()
                row['alternative_codes'] = '|'.join(row['alternative_codes'])
                writer.writerow(row)
    
    def generate_html_report(self, report: AuditReport) -> str:
        """
        Genera reporte en HTML
        
        Args:
            report: AuditReport a convertir
            
        Returns:
            String con HTML
        """
        stats = self.get_summary_statistics(report)
        
        html = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reporte de Auditoría - {report.audit_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .summary {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-bottom: 20px; }}
                .metric {{ background: white; padding: 15px; border-left: 4px solid #3498db; border-radius: 5px; }}
                .metric.success {{ border-left-color: #27ae60; }}
                .metric.warning {{ border-left-color: #f39c12; }}
                .metric.danger {{ border-left-color: #e74c3c; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
                .metric-label {{ color: #7f8c8d; font-size: 14px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; margin-top: 20px; }}
                th {{ background: #34495e; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 12px; border-bottom: 1px solid #ecf0f1; }}
                tr:hover {{ background: #ecf0f1; }}
                .status-correct {{ color: #27ae60; font-weight: bold; }}
                .status-warning {{ color: #f39c12; font-weight: bold; }}
                .status-danger {{ color: #e74c3c; font-weight: bold; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ecf0f1; color: #7f8c8d; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Reporte de Auditoría de Códigos CIE-10</h1>
                <p>ID: {report.audit_id}</p>
                <p>Fecha: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            
            <div class="summary">
                <div class="metric success">
                    <div class="metric-value">{stats['conformity_percentage']:.1f}%</div>
                    <div class="metric-label">Conformidad General</div>
                </div>
                <div class="metric">
                    <div class="metric-value">{report.total_records}</div>
                    <div class="metric-label">Total Auditados</div>
                </div>
                <div class="metric success">
                    <div class="metric-value">{report.total_correct}</div>
                    <div class="metric-label">Códigos Correctos</div>
                </div>
                <div class="metric danger">
                    <div class="metric-value">{report.total_mismatch + report.total_not_found}</div>
                    <div class="metric-label">Problemas Críticos</div>
                </div>
            </div>
            
            <h2>Desglose de Resultados</h2>
            <table>
                <tr>
                    <th>Categoría</th>
                    <th>Cantidad</th>
                    <th>Porcentaje</th>
                </tr>
                <tr>
                    <td><span class="status-correct">✓ Correcto</span></td>
                    <td>{stats['breakdown']['correct']['count']}</td>
                    <td>{stats['breakdown']['correct']['percentage']}%</td>
                </tr>
                <tr>
                    <td><span class="status-warning">~ Coincidencia Parcial</span></td>
                    <td>{stats['breakdown']['partial_match']['count']}</td>
                    <td>{stats['breakdown']['partial_match']['percentage']}%</td>
                </tr>
                <tr>
                    <td><span class="status-warning">⚠️ Alternativa</span></td>
                    <td>{stats['breakdown']['alternative']['count']}</td>
                    <td>{stats['breakdown']['alternative']['percentage']}%</td>
                </tr>
                <tr>
                    <td><span class="status-danger">✗ No Coincide</span></td>
                    <td>{stats['breakdown']['mismatch']['count']}</td>
                    <td>{stats['breakdown']['mismatch']['percentage']}%</td>
                </tr>
                <tr>
                    <td><span class="status-danger">? No Encontrado</span></td>
                    <td>{stats['breakdown']['not_found']['count']}</td>
                    <td>{stats['breakdown']['not_found']['percentage']}%</td>
                </tr>
            </table>
            
            <h2>Hallazgos Críticos</h2>
            <table>
                <tr>
                    <th>Paciente</th>
                    <th>Diagnóstico</th>
                    <th>Código Asignado</th>
                    <th>Código Sugerido</th>
                    <th>Tipo</th>
                    <th>Confianza</th>
                </tr>
        """
        
        # Incluir solo hallazgos críticos (mismatch y not_found)
        for finding in report.findings:
            if finding.discrepancy_type in [DiscrepancyType.MISMATCH, DiscrepancyType.NOT_FOUND]:
                status_class = "status-danger"
                html += f"""
                <tr>
                    <td>{finding.patient_id}</td>
                    <td>{finding.diagnosis_text}</td>
                    <td>{finding.assigned_code}</td>
                    <td>{finding.suggested_code or 'N/A'}</td>
                    <td><span class="{status_class}">{finding.discrepancy_type.value}</span></td>
                    <td>{finding.confidence_score:.2%}</td>
                </tr>
                """
        
        html += """
            </table>
            
            <div class="footer">
                <p>Reporte generado automáticamente por Clinic Classifier</p>
                <p>Sistema de Clasificación de Diagnósticos CIE-10</p>
            </div>
        </body>
        </html>
        """
        
        return html
