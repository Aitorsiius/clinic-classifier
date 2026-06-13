"""Tests de los endpoints del ``audit-service`` con la autenticación y el
auditor simulados.

Se sustituye la dependencia ``verify_token`` (para no llamar al gateway), se
simula ``httpx.AsyncClient`` y se inyecta un ``CodeAuditor`` falso que devuelve
un informe determinista, cubriendo ``/audit/batch``, ``/audit/batch-stream``,
``/audit/record`` y ``/audit/{audit_id}``.
"""
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data if data is not None else {}

    def json(self):
        return self._data


class FakeAsyncClient:
    routes: dict = {}
    default = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    def _resolve(self, url):
        for key, val in FakeAsyncClient.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        return FakeAsyncClient.default or FakeResp(200, {"results": []})

    async def post(self, url, **k):
        return self._resolve(url)

    async def get(self, url, **k):
        return self._resolve(url)


class _Finding:
    def __init__(self):
        self.patient_id = "PAT0000"
        self.diagnosis_text = "tos persistente"
        self.assigned_code = "A00.0"
        self.suggested_code = "A00.0"
        self.discrepancy_type = main.DiscrepancyType.CORRECT
        self.confidence_score = 0.9
        self.match_score = 1.0
        self.explanation = "coincidencia"
        self.alternative_codes = []


class _Report:
    def __init__(self, n=1):
        self.audit_id = "aud-1"
        self.timestamp = datetime.now(timezone.utc)
        self.total_records = n
        self.total_correct = n
        self.total_partial_match = 0
        self.total_mismatch = 0
        self.conformity_percentage = 100.0 if n else 0.0
        self.total_time_ms = 12.345
        self.findings = [_Finding() for _ in range(n)]


class FakeAuditor:
    def __init__(self, engine):
        pass

    def audit_batch(self, records, algorithm=None, top_k=5, progress_callback=None, use_ai=False):
        if progress_callback:
            progress_callback(1, max(1, len(records)))
        return _Report(len(records))


@pytest.fixture
def auth():
    """Sustituye la verificación de token por un usuario fijo."""
    main.app.dependency_overrides[main.verify_token] = lambda: "u@test.com"
    yield
    main.app.dependency_overrides.pop(main.verify_token, None)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(main, "CodeAuditor", FakeAuditor)
    FakeAsyncClient.routes = {}
    FakeAsyncClient.default = None
    yield
    FakeAsyncClient.routes = {}
    FakeAsyncClient.default = None


_REC = {"records": [{"diagnosis_text": "tos", "assigned_code": "A00.0", "patient_id": "P1"}]}


# ---------------------------------------------------------------------------
# /audit/batch
# ---------------------------------------------------------------------------
def test_batch_success(auth):
    resp = client.post("/audit/batch", json=_REC)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_records"] == 1
    assert body["conformity_percentage"] == 100.0
    assert body["findings"][0]["suggested_code"] == "A00.0"


def test_batch_requires_auth():
    # Sin override y sin cabecera Authorization -> 401 en verify_token.
    resp = client.post("/audit/batch", json=_REC)
    assert resp.status_code == 401


def test_batch_logs_to_log_service(auth):
    # La llamada al log-service usa el cliente simulado (default 200): no rompe.
    FakeAsyncClient.routes = {"/audits": FakeResp(200, {})}
    resp = client.post("/audit/batch", json=_REC)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /audit/batch-stream (SSE)
# ---------------------------------------------------------------------------
def test_batch_stream_success(auth):
    resp = client.post("/audit/batch-stream", json=_REC)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type": "complete"' in resp.text


def test_batch_stream_requires_auth():
    assert client.post("/audit/batch-stream", json=_REC).status_code == 401


# ---------------------------------------------------------------------------
# /audit/record
# ---------------------------------------------------------------------------
def _audit_result_payload():
    return {
        "patient_id": "P1", "diagnosis_text": "tos", "assigned_code": "A00.0",
        "suggested_code": "A00.0", "discrepancy_type": "coincidencia",
        "confidence_score": 0.9, "match_score": 1.0, "explanation": "ok",
        "alternative_codes": [],
    }


def test_audit_record_success(auth):
    FakeAsyncClient.routes = {"/api/audit/record": FakeResp(200, _audit_result_payload())}
    resp = client.post("/audit/record", json={"diagnosis_text": "tos", "assigned_code": "A00.0"})
    assert resp.status_code == 200
    assert resp.json()["suggested_code"] == "A00.0"


def test_audit_record_upstream_error(auth):
    FakeAsyncClient.routes = {"/api/audit/record": FakeResp(500, {})}
    resp = client.post("/audit/record", json={"diagnosis_text": "tos", "assigned_code": "A00.0"})
    assert resp.status_code == 500


def test_audit_record_backend_unavailable(auth):
    FakeAsyncClient.routes = {"/api/audit/record": httpx.RequestError("down")}
    resp = client.post("/audit/record", json={"diagnosis_text": "tos", "assigned_code": "A00.0"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /audit/{audit_id}
# ---------------------------------------------------------------------------
def _report_payload():
    return {
        "audit_id": "aud-1", "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_records": 1, "total_correct": 1, "total_partial_match": 0,
        "total_mismatch": 0, "conformity_percentage": 100.0, "top_k": 5,
        "total_time_ms": 5.0, "findings": [_audit_result_payload()],
    }


def test_get_audit_report_success(auth):
    FakeAsyncClient.routes = {"/api/audit/aud-1": FakeResp(200, _report_payload())}
    resp = client.get("/audit/aud-1")
    assert resp.status_code == 200
    assert resp.json()["audit_id"] == "aud-1"


def test_get_audit_report_not_found(auth):
    FakeAsyncClient.routes = {"/api/audit/missing": FakeResp(404, {})}
    resp = client.get("/audit/missing")
    assert resp.status_code == 404


def test_get_audit_report_backend_unavailable(auth):
    FakeAsyncClient.routes = {"/api/audit/x": httpx.RequestError("down")}
    resp = client.get("/audit/x")
    assert resp.status_code == 503
