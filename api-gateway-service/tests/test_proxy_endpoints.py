"""Tests de los endpoints *proxy* del gateway con ``httpx`` simulado.

Cubren los flujos hacia el auth-service, backend, audit-service, log-service,
history-service y procesador LLM: caminos de éxito, errores de estado y errores
de transporte (timeout / conexión), que son la mayor parte del código del
gateway.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)
AUTH = {"Authorization": f"Bearer {main.create_token('admin')}"}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class FakeStreamResponse:
    """Respuesta de ``client.stream(...)``: expone ``status_code`` y
    ``aiter_lines`` para emular el SSE del audit-service."""

    def __init__(self, status_code=200, lines=None):
        self.status_code = status_code
        self._lines = lines or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeAsyncClient:
    """``AsyncClient`` simulado: enruta por subcadena de URL a una respuesta,
    una excepción (para los caminos de error) o un *callable*."""

    routes: dict = {}
    # Configuración del stream SSE (status y líneas a emitir / o excepción).
    stream_status: int = 200
    stream_lines: list = []
    stream_error: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _resolve(self, url):
        for key, val in FakeAsyncClient.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                if callable(val):
                    return val()
                return val
        return FakeResponse(200, {})

    async def post(self, url, **kwargs):
        return self._resolve(url)

    async def get(self, url, **kwargs):
        return self._resolve(url)

    async def patch(self, url, **kwargs):
        return self._resolve(url)

    async def request(self, method, url, **kwargs):
        return self._resolve(url)

    def stream(self, method, url, **kwargs):
        if FakeAsyncClient.stream_error is not None:
            raise FakeAsyncClient.stream_error
        return FakeStreamResponse(FakeAsyncClient.stream_status, FakeAsyncClient.stream_lines)


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.routes = {}
    FakeAsyncClient.stream_status = 200
    FakeAsyncClient.stream_lines = []
    FakeAsyncClient.stream_error = None
    yield
    FakeAsyncClient.routes = {}
    FakeAsyncClient.stream_error = None


def _routes(mapping):
    FakeAsyncClient.routes = mapping


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------
def test_health_all_ok():
    _routes({
        "/health": FakeResponse(200, {"status": "healthy"}),
    })
    body = client.get("/health").json()
    assert body["gateway"] == "healthy"
    assert body["backend"] == {"status": "healthy"}


def test_health_backend_down_returns_503():
    _routes({f"{main.BACKEND_URL}/health": Exception("backend down")})
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json()["gateway"] == "healthy"


# ----------------------------------------------------------------------------
# /api/login
# ----------------------------------------------------------------------------
def test_login_success_adds_session_id():
    _routes({
        "/auth/login": FakeResponse(200, {
            "access_token": "tok", "token_type": "bearer", "expires_in": 3600,
            "user_data": {"user_id": "u1"},
        }),
        "/sessions/create": FakeResponse(200, {"session_id": "sess-1"}),
    })
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "tok"
    assert body["session_id"] == "sess-1"


def test_login_invalid_credentials_401():
    _routes({"/auth/login": FakeResponse(401, {"detail": "Credenciales inválidas"})})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 401


def test_login_auth_service_unavailable_503():
    _routes({"/auth/login": httpx.ConnectError("no auth")})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 503


def test_login_session_creation_failure_is_tolerated():
    _routes({
        "/auth/login": FakeResponse(200, {
            "access_token": "tok", "token_type": "bearer", "expires_in": 3600,
            "user_data": {"user_id": "u1"},
        }),
        "/sessions/create": Exception("log down"),
    })
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "unknown"


# ----------------------------------------------------------------------------
# /api/logout
# ----------------------------------------------------------------------------
def test_logout_with_session_id():
    _routes({"/sessions/close": FakeResponse(200, {})})
    resp = client.post("/api/logout?session_id=sess-1", headers=AUTH)
    assert resp.status_code == 200
    assert "logged out" in resp.json()["message"]


def test_logout_without_auth_401():
    assert client.post("/api/logout").status_code == 401


# ----------------------------------------------------------------------------
# /api/search
# ----------------------------------------------------------------------------
def test_search_success():
    _routes({f"{main.BACKEND_URL}/search": FakeResponse(200, {"results": [], "count": 0})})
    resp = client.post("/api/search", json={"query": "tos", "top_k": 3})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_search_backend_error_propagates():
    _routes({f"{main.BACKEND_URL}/search": FakeResponse(500, {"detail": "boom"})})
    resp = client.post("/api/search", json={"query": "tos"})
    assert resp.status_code == 500


def test_search_timeout_504():
    _routes({f"{main.BACKEND_URL}/search": httpx.TimeoutException("slow")})
    resp = client.post("/api/search", json={"query": "tos"})
    assert resp.status_code == 504


def test_search_connect_error_503():
    _routes({f"{main.BACKEND_URL}/search": httpx.ConnectError("down")})
    resp = client.post("/api/search", json={"query": "tos"})
    assert resp.status_code == 503


# ----------------------------------------------------------------------------
# /api/audit/batch
# ----------------------------------------------------------------------------
def test_audit_batch_success():
    _routes({"/audit/batch": FakeResponse(200, {"findings": [], "total_time_ms": 5})})
    resp = client.post(
        "/api/audit/batch",
        json={"records": [{"diagnosis_text": "x", "assigned_code": "A00.0"}]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["user_username"] == "admin"


def test_audit_batch_empty_records_400():
    resp = client.post("/api/audit/batch", json={"records": []}, headers=AUTH)
    assert resp.status_code == 400


def test_audit_batch_requires_auth():
    resp = client.post(
        "/api/audit/batch",
        json={"records": [{"diagnosis_text": "x", "assigned_code": "A00.0"}]},
    )
    assert resp.status_code == 401


def test_audit_batch_timeout_504():
    _routes({"/audit/batch": httpx.TimeoutException("slow")})
    resp = client.post(
        "/api/audit/batch",
        json={"records": [{"diagnosis_text": "x", "assigned_code": "A00.0"}]},
        headers=AUTH,
    )
    assert resp.status_code == 504


# ----------------------------------------------------------------------------
# Procesador LLM: /api/analyze-query, /api/correct-query, /api/process-query
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("path,endpoint", [
    ("/api/analyze-query", "/analyze"),
    ("/api/correct-query", "/correct"),
    ("/api/process-query", "/process"),
])
def test_llm_proxy_success(path, endpoint):
    _routes({endpoint: FakeResponse(200, {"ok": True})})
    resp = client.post(path, json={"query": "tos"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_llm_proxy_timeout_504():
    _routes({"/analyze": httpx.TimeoutException("slow")})
    resp = client.post("/api/analyze-query", json={"query": "tos"})
    assert resp.status_code == 504


def test_llm_proxy_connect_error_503():
    _routes({"/correct": httpx.ConnectError("down")})
    resp = client.post("/api/correct-query", json={"query": "tos"})
    assert resp.status_code == 503


def test_llm_proxy_upstream_error_propagates():
    _routes({"/process": FakeResponse(502, {"detail": "bad gateway"})})
    resp = client.post("/api/process-query", json={"query": "tos"})
    assert resp.status_code == 502


# ----------------------------------------------------------------------------
# /api/log/update-ai (degrada con warnings, nunca 5xx)
# ----------------------------------------------------------------------------
def test_update_ai_success():
    _routes({"/searches/update-ai": FakeResponse(200, {"status": "ok"})})
    resp = client.patch("/api/log/update-ai", json={"session_id": "s", "query": "q"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_update_ai_failure_returns_warning():
    _routes({"/searches/update-ai": FakeResponse(500, {})})
    resp = client.patch("/api/log/update-ai", json={"session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "warning"


def test_update_ai_connect_error_returns_warning():
    _routes({"/searches/update-ai": httpx.ConnectError("down")})
    resp = client.patch("/api/log/update-ai", json={"session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "warning"


# ----------------------------------------------------------------------------
# Endpoints de administración (delegados al auth-service)
# ----------------------------------------------------------------------------
def test_admin_list_users_success():
    _routes({"/admin/users": FakeResponse(200, {"users": []})})
    resp = client.get("/api/admin/users", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"users": []}


def test_admin_requires_auth_header():
    assert client.get("/api/admin/users").status_code == 401


def test_admin_create_user_success():
    _routes({"/admin/users": FakeResponse(200, {"created": True})})
    resp = client.post("/api/admin/users", json={"username": "n"}, headers=AUTH)
    assert resp.status_code == 200


def test_admin_forbidden_maps_403():
    _routes({"/admin/users": FakeResponse(403, {})})
    resp = client.get("/api/admin/users", headers=AUTH)
    assert resp.status_code == 403


def test_admin_auth_service_unavailable_503():
    _routes({"/admin/users": httpx.ConnectError("down")})
    resp = client.get("/api/admin/users", headers=AUTH)
    assert resp.status_code == 503


def test_admin_update_role_success():
    _routes({"/role": FakeResponse(200, {"updated": True})})
    resp = client.put("/api/admin/users/bob/role", json={"admin": True}, headers=AUTH)
    assert resp.status_code == 200


def test_admin_unblock_user_success():
    _routes({"/unblock": FakeResponse(200, {"unblocked": True})})
    resp = client.post("/api/admin/users/bob/unblock", headers=AUTH)
    assert resp.status_code == 200


def test_admin_delete_user_success():
    _routes({"/admin/users/bob": FakeResponse(200, {"deleted": True})})
    resp = client.delete("/api/admin/users/bob", headers=AUTH)
    assert resp.status_code == 200


def test_admin_block_info_success():
    _routes({"/block-info": FakeResponse(200, {"attempts": []})})
    resp = client.get("/api/admin/users/bob/block-info", headers=AUTH)
    assert resp.status_code == 200


# ----------------------------------------------------------------------------
# /api/search-history
# ----------------------------------------------------------------------------
def test_search_history_success():
    _routes({"/history": FakeResponse(200, {"segments": []})})
    resp = client.get("/api/search-history", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"segments": []}


def test_search_history_requires_auth():
    assert client.get("/api/search-history").status_code == 401


def test_search_history_upstream_error():
    _routes({"/history": FakeResponse(500, {})})
    resp = client.get("/api/search-history", headers=AUTH)
    assert resp.status_code == 500


def test_search_history_timeout_504():
    _routes({"/history": httpx.TimeoutException("slow")})
    resp = client.get("/api/search-history", headers=AUTH)
    assert resp.status_code == 504


# ----------------------------------------------------------------------------
# /api/audit/batch-stream (SSE)
# ----------------------------------------------------------------------------
_REC = {"records": [{"diagnosis_text": "x", "assigned_code": "A00.0"}]}


def test_audit_stream_empty_records_400():
    resp = client.post("/api/audit/batch-stream", json={"records": []}, headers=AUTH)
    assert resp.status_code == 400


def test_audit_stream_requires_auth():
    assert client.post("/api/audit/batch-stream", json=_REC).status_code == 401


def test_audit_stream_success_emits_events_and_logs():
    complete = 'data: {"type": "complete", "result": {"audit_id": "a1", "total_records": 1, "findings": []}}'
    FakeAsyncClient.stream_status = 200
    FakeAsyncClient.stream_lines = ['data: {"type": "progress", "current": 1}', complete]
    resp = client.post(
        "/api/audit/batch-stream",
        json=_REC,
        headers={**AUTH, "x-session-id": "s1", "x-user-id": "u1"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type": "complete"' in resp.text


def test_audit_stream_upstream_error_emits_error_event():
    FakeAsyncClient.stream_status = 500
    FakeAsyncClient.stream_lines = []
    resp = client.post("/api/audit/batch-stream", json=_REC, headers=AUTH)
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text


def test_audit_stream_connect_error_emits_error_event():
    FakeAsyncClient.stream_error = httpx.ConnectError("down")
    resp = client.post("/api/audit/batch-stream", json=_REC, headers=AUTH)
    assert resp.status_code == 200
    assert "Cannot connect to audit service" in resp.text


def test_audit_stream_timeout_emits_error_event():
    FakeAsyncClient.stream_error = httpx.TimeoutException("slow")
    resp = client.post("/api/audit/batch-stream", json=_REC, headers=AUTH)
    assert resp.status_code == 200
    assert "Request timeout" in resp.text

