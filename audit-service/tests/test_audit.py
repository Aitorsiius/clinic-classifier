"""Tests unitarios del módulo de auditoría (``audit.py``).

Cubren la lógica de comparación de códigos CIE-10, la agregación por lotes y el
wrapper de búsqueda contra el gateway (con httpx simulado). No requieren red ni
base de datos.
"""
import audit
from audit import (
    AuditFinding,
    CodeAuditor,
    DiagnosisRecord,
    DiscrepancyType,
    GatewaySearchEngine,
)


class FakeSearchEngine:
    """Motor de búsqueda simulado que devuelve resultados predefinidos."""

    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, query, top_k=5, algorithm="hybrid", use_ai=False):
        self.calls.append((query, top_k, algorithm, use_ai))
        return self._results


def _result(code, score):
    return {"payload": {"id": code}, "score": score}


# ----------------------------------------------------------------------------
# Enum y dataclasses
# ----------------------------------------------------------------------------
def test_discrepancy_type_values():
    assert DiscrepancyType.CORRECT.value == "coincidencia"
    assert DiscrepancyType.PARTIAL_MATCH.value == "parcialmente"
    assert DiscrepancyType.MISMATCH.value == "no_coincidencia"


def test_diagnosis_record_to_dict():
    rec = DiagnosisRecord(diagnosis_text="dolor", assigned_code="A00.0", patient_id="p1")
    d = rec.to_dict()
    assert d["diagnosis_text"] == "dolor"
    assert d["assigned_code"] == "A00.0"
    assert d["patient_id"] == "p1"


def test_audit_finding_to_dict_serializes_enum():
    finding = AuditFinding(
        patient_id="p1",
        diagnosis_text="x",
        assigned_code="A00",
        suggested_code="A00",
        discrepancy_type=DiscrepancyType.CORRECT,
        confidence_score=1.0,
        match_score=1.0,
        explanation="ok",
        alternative_codes=[],
    )
    assert finding.to_dict()["discrepancy_type"] == "coincidencia"


# ----------------------------------------------------------------------------
# audit_record / _compare_codes
# ----------------------------------------------------------------------------
def test_exact_match_is_correct():
    engine = FakeSearchEngine([_result("A00.0", 0.95), _result("A00.1", 0.5)])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="colera", assigned_code="A00.0", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.CORRECT
    assert finding.suggested_code == "A00.0"
    assert finding.alternative_codes == ["A00.1"]


def test_partial_match_same_main_category():
    engine = FakeSearchEngine([_result("A00.1", 0.9)])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="x", assigned_code="A00.9", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.PARTIAL_MATCH


def test_mismatch_unrelated_code():
    engine = FakeSearchEngine([_result("A00.1", 0.9)])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="x", assigned_code="Z99", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.MISMATCH
    assert finding.confidence_score == 0.9
    assert finding.match_score == 0.0


def test_no_results_is_mismatch():
    engine = FakeSearchEngine([])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="x", assigned_code="A00", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.MISMATCH
    assert finding.suggested_code == ""
    assert finding.explanation


def test_special_same_score_logic_is_correct():
    # El código asignado aparece en posición > 0 y todos los anteriores
    # comparten la misma puntuación -> se considera coincidencia.
    engine = FakeSearchEngine([_result("A00.0", 0.8), _result("A00.1", 0.8)])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="x", assigned_code="A00.1", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.CORRECT


def test_found_but_different_category_is_partial():
    engine = FakeSearchEngine([_result("B10", 0.9), _result("A00", 0.4)])
    auditor = CodeAuditor(engine)
    rec = DiagnosisRecord(diagnosis_text="x", assigned_code="A00", patient_id="p1")
    finding = auditor.audit_record(rec)
    assert finding.discrepancy_type == DiscrepancyType.PARTIAL_MATCH
    assert finding.match_score == 0.4


# ----------------------------------------------------------------------------
# _check_previous_results_same_score
# ----------------------------------------------------------------------------
def test_check_previous_same_score_true():
    auditor = CodeAuditor(FakeSearchEngine([]))
    results = [_result("A", 0.8), _result("B", 0.8)]
    assert auditor._check_previous_results_same_score(results, 1, 0.8) is True


def test_check_previous_same_score_position_zero_is_false():
    auditor = CodeAuditor(FakeSearchEngine([]))
    results = [_result("A", 0.8)]
    assert auditor._check_previous_results_same_score(results, 0, 0.8) is False


def test_check_previous_same_score_different_is_false():
    auditor = CodeAuditor(FakeSearchEngine([]))
    results = [_result("A", 0.7), _result("B", 0.8)]
    assert auditor._check_previous_results_same_score(results, 1, 0.8) is False


# ----------------------------------------------------------------------------
# audit_batch
# ----------------------------------------------------------------------------
def test_audit_batch_aggregates_and_reports_progress():
    engine = FakeSearchEngine([_result("A00.0", 0.95)])
    auditor = CodeAuditor(engine)
    records = [
        DiagnosisRecord(diagnosis_text="x", assigned_code="A00.0", patient_id="p1"),
        DiagnosisRecord(diagnosis_text="y", assigned_code="Z99", patient_id="p2"),
    ]
    progress = []
    report = auditor.audit_batch(
        records, top_k=5, progress_callback=lambda c, t: progress.append((c, t))
    )
    assert report.total_records == 2
    assert report.total_correct == 1
    assert report.total_mismatch == 1
    assert progress == [(1, 2), (2, 2)]
    assert report.audit_id in auditor.audit_history
    assert report.conformity_percentage == 50.0
    as_dict = report.to_dict()
    assert as_dict["total_records"] == 2
    assert "findings" in as_dict


# ----------------------------------------------------------------------------
# GatewaySearchEngine (httpx simulado)
# ----------------------------------------------------------------------------
def _patch_httpx_client(monkeypatch, response=None, raises=None):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            if raises is not None:
                raise raises
            return FakeResponse(*response)

        def close(self):
            pass

    monkeypatch.setattr(audit.httpx, "Client", FakeClient)


def test_gateway_search_success(monkeypatch):
    _patch_httpx_client(
        monkeypatch, response=(200, {"results": [{"payload": {"id": "A00"}, "score": 0.9}]})
    )
    engine = GatewaySearchEngine("http://gw")
    results = engine.search("dolor")
    assert results == [{"payload": {"id": "A00"}, "score": 0.9}]


def test_gateway_search_http_error_returns_empty(monkeypatch):
    _patch_httpx_client(monkeypatch, response=(500, {}))
    engine = GatewaySearchEngine("http://gw")
    assert engine.search("x") == []


def test_gateway_search_exception_returns_empty(monkeypatch):
    _patch_httpx_client(monkeypatch, raises=RuntimeError("boom"))
    engine = GatewaySearchEngine("http://gw")
    assert engine.search("x") == []


# ----------------------------------------------------------------------------
# Smoke test: importar la app FastAPI del servicio
# ----------------------------------------------------------------------------
def test_service_app_imports():
    import main

    assert hasattr(main, "app")
