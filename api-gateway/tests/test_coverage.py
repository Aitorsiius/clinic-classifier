"""Tests de cobertura para ``api-gateway/main.py``.

Cubren las ramas que el resto de la suite no toca: helpers de configuración y
autenticación, logging no-bloqueante (URL ausente / timeout), parseo de eventos
SSE, y las ramas de error/paso de parámetros de los endpoints proxy (login,
logout, audit, search, LLM, admin e historial).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)
AUTH = {"Authorization": f"Bearer {main.create_token('admin')}"}
_REC = {"records": [{"diagnosis_text": "x", "assigned_code": "A00.0"}]}


# ---------------------------------------------------------------------------
# Dobles de httpx
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class BoomJSONResponse:
    """Respuesta 200 cuyo ``.json()`` lanza (para las ramas ``except`` genéricas)."""

    status_code = 200

    def json(self):
        raise ValueError("json inválido")


class FakeStreamResponse:
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
    routes: dict = {}
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


# ===========================================================================
# Helpers de configuración / autenticación
# ===========================================================================
def test_require_env_missing_raises(monkeypatch):
    monkeypatch.delenv("NO_EXISTE_ESTA_VAR", raising=False)
    with pytest.raises(RuntimeError):
        main._require_env("NO_EXISTE_ESTA_VAR")


def test_is_valid_cors_origin_bad_scheme():
    assert main._is_valid_cors_origin("ftp://localhost") is False


def test_is_valid_cors_origin_no_netloc():
    assert main._is_valid_cors_origin("https://") is False


def test_is_valid_cors_origin_dangerous_chars():
    assert main._is_valid_cors_origin("https://ev<il>.com") is False


def test_is_valid_cors_origin_ok():
    assert main._is_valid_cors_origin("https://localhost:3000") is True


def test_get_current_user_token_without_username():
    token = jwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        main.JWT_SECRET,
        algorithm=main.JWT_ALGORITHM,
    )
    resp = client.get("/api/verify-token", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ===========================================================================
# Parseo de eventos SSE
# ===========================================================================
def test_extract_audit_result_non_data_line():
    assert main._extract_audit_result_from_sse("evento raro sin prefijo") is None


def test_extract_audit_result_invalid_json():
    # Evento 'complete' pero con JSON malformado -> None (rama JSONDecodeError).
    line = 'data: {"type": "complete" ROTO}'
    assert main._extract_audit_result_from_sse(line) is None


# ===========================================================================
# log_search / log_audit / _log_successful_audit (asíncronos)
# ===========================================================================
class _TimeoutClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def post(self, *a, **k):
        raise asyncio.TimeoutError()


def test_log_search_no_service_url(monkeypatch):
    monkeypatch.setattr(main, "LOG_SERVICE_URL", "")
    asyncio.run(main.log_search("s", "u", "q"))


def test_log_search_timeout(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _TimeoutClient)
    asyncio.run(main.log_search("s", "u", "q"))


def test_log_audit_no_service_url(monkeypatch):
    monkeypatch.setattr(main, "LOG_SERVICE_URL", "")
    asyncio.run(main.log_audit("s", "u", 1))


def test_log_audit_timeout(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _TimeoutClient)
    asyncio.run(main.log_audit("s", "u", 1))


def test_log_successful_audit_early_return():
    # Sin session_id/user_id/audit_result -> return inmediato.
    asyncio.run(main._log_successful_audit(None, None, None, None, None))


# ===========================================================================
# /health — LLM processor caído
# ===========================================================================
def test_health_llm_processor_unhealthy():
    _routes({
        f"{main.BACKEND_URL}/health": FakeResponse(200, {"status": "healthy"}),
        f"{main.LLM_QUERY_PROCESSOR_URL}/health": Exception("llm down"),
    })
    body = client.get("/health").json()
    assert body["backend"] == {"status": "healthy"}
    assert body["llm_processor"] == {"status": "unhealthy"}


# ===========================================================================
# /api/login — ramas de error
# ===========================================================================
def test_login_401_strips_status_prefix():
    _routes({"/auth/login": FakeResponse(401, {"detail": "401: Credenciales inválidas"})})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Credenciales inválidas"


def test_login_non_200_error_propagates():
    _routes({"/auth/login": FakeResponse(500, {"detail": "500: fallo interno"})})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "fallo interno"


def test_login_non_200_error_without_status_prefix():
    # detail sin prefijo "500:" -> no se recorta (cubre la otra rama).
    _routes({"/auth/login": FakeResponse(502, {"detail": "bad gateway"})})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 502
    assert resp.json()["detail"] == "bad gateway"


def test_login_session_creation_non_200_is_tolerated():
    _routes({
        "/auth/login": FakeResponse(200, {
            "access_token": "tok", "token_type": "bearer", "expires_in": 3600,
            "user_data": {"user_id": "u1"},
        }),
        "/sessions/create": FakeResponse(500, {}),
    })
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 200
    # session_id queda a None cuando el log-service responde !=200.
    assert resp.json()["session_id"] is None


def test_login_generic_error_returns_500():
    _routes({"/auth/login": BoomJSONResponse()})
    resp = client.post("/api/login", json={"username": "a", "password": "b"})
    assert resp.status_code == 500


# ===========================================================================
# /api/logout — ramas
# ===========================================================================
def test_logout_without_session_id():
    resp = client.post("/api/logout", headers=AUTH)
    assert resp.status_code == 200
    assert "logged out" in resp.json()["message"]


def test_logout_session_close_error_is_tolerated():
    _routes({"/sessions/close": Exception("log down")})
    resp = client.post("/api/logout?session_id=sess-1", headers=AUTH)
    assert resp.status_code == 200


# ===========================================================================
# /api/audit/batch — ramas
# ===========================================================================
def test_audit_batch_with_params_logs(monkeypatch):
    logged = {}

    async def fake_log_audit(**kwargs):
        logged.update(kwargs)

    monkeypatch.setattr(main, "log_audit", fake_log_audit)
    _routes({"/audit/batch": FakeResponse(200, {"findings": [], "total_time_ms": 7})})
    resp = client.post(
        "/api/audit/batch?session_id=s1&user_id=u1", json=_REC, headers=AUTH
    )
    assert resp.status_code == 200
    assert logged["session_id"] == "s1"
    assert logged["user_id"] == "u1"


def test_audit_batch_upstream_error_propagates():
    _routes({"/audit/batch": FakeResponse(500, {"detail": "boom"})})
    resp = client.post("/api/audit/batch", json=_REC, headers=AUTH)
    assert resp.status_code == 500


def test_audit_batch_connect_error_503():
    _routes({"/audit/batch": httpx.ConnectError("down")})
    resp = client.post("/api/audit/batch", json=_REC, headers=AUTH)
    assert resp.status_code == 503


def test_audit_batch_generic_error_500():
    _routes({"/audit/batch": BoomJSONResponse()})
    resp = client.post("/api/audit/batch", json=_REC, headers=AUTH)
    assert resp.status_code == 500


# ===========================================================================
# /api/audit/batch-stream — ramas del generador
# ===========================================================================
def test_audit_stream_skips_non_data_lines_and_no_complete():
    FakeAsyncClient.stream_status = 200
    FakeAsyncClient.stream_lines = [
        "linea sin prefijo data",
        'data: {"type": "progress", "current": 1}',
    ]
    resp = client.post("/api/audit/batch-stream", json=_REC, headers=AUTH)
    assert resp.status_code == 200
    assert '"type": "progress"' in resp.text


def test_audit_stream_generic_error_emits_internal_error():
    FakeAsyncClient.stream_error = RuntimeError("boom")
    resp = client.post("/api/audit/batch-stream", json=_REC, headers=AUTH)
    assert resp.status_code == 200
    assert "Internal server error" in resp.text


# ===========================================================================
# /api/search — ramas
# ===========================================================================
def test_search_with_params_query():
    _routes({f"{main.BACKEND_URL}/search": FakeResponse(200, {"results": [], "count": 0})})
    resp = client.post(
        "/api/search?session_id=s1&user_id=u1", json={"query": "tos"}
    )
    assert resp.status_code == 200


def test_search_generic_error_500():
    _routes({f"{main.BACKEND_URL}/search": BoomJSONResponse()})
    resp = client.post("/api/search", json={"query": "tos"})
    assert resp.status_code == 500


def test_search_alias_endpoint():
    # El alias /search reenvía a search_diagnosis con el Request correcto.
    _routes({f"{main.BACKEND_URL}/search": FakeResponse(200, {"results": [], "count": 0})})
    resp = client.post("/search", json={"query": "tos"})
    assert resp.status_code == 200


# ===========================================================================
# Procesador LLM — rama genérica
# ===========================================================================
def test_llm_proxy_generic_error_500():
    _routes({"/analyze": BoomJSONResponse()})
    resp = client.post("/api/analyze-query", json={"query": "tos"})
    assert resp.status_code == 500


# ===========================================================================
# /api/log/update-ai — ramas
# ===========================================================================
def test_update_ai_timeout_returns_warning():
    _routes({"/searches/update-ai": httpx.TimeoutException("slow")})
    resp = client.patch("/api/log/update-ai", json={"session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "warning"


def test_update_ai_generic_error_returns_warning():
    _routes({"/searches/update-ai": BoomJSONResponse()})
    resp = client.patch("/api/log/update-ai", json={"session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "warning"


# ===========================================================================
# Endpoints de administración — ramas
# ===========================================================================
def test_admin_forwards_session_header():
    _routes({"/admin/users": FakeResponse(200, {"created": True})})
    resp = client.post(
        "/api/admin/users",
        json={"username": "n"},
        headers={**AUTH, "x-session-id": "sess-1"},
    )
    assert resp.status_code == 200


def test_admin_non_200_non_403_propagates():
    _routes({"/admin/users": FakeResponse(400, {"detail": "petición inválida"})})
    resp = client.get("/api/admin/users", headers=AUTH)
    assert resp.status_code == 400


def test_admin_generic_error_500():
    _routes({"/admin/users": BoomJSONResponse()})
    resp = client.get("/api/admin/users", headers=AUTH)
    assert resp.status_code == 500


def test_admin_change_password_success():
    _routes({"/password": FakeResponse(200, {"changed": True})})
    resp = client.put(
        "/api/admin/users/bob/password", json={"password": "x"}, headers=AUTH
    )
    assert resp.status_code == 200


# ===========================================================================
# /api/search-history — ramas
# ===========================================================================
def test_search_history_connect_error_503():
    _routes({"/history": httpx.ConnectError("down")})
    resp = client.get("/api/search-history", headers=AUTH)
    assert resp.status_code == 503


def test_search_history_generic_error_500():
    _routes({"/history": BoomJSONResponse()})
    resp = client.get("/api/search-history", headers=AUTH)
    assert resp.status_code == 500
