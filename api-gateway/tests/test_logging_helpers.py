"""Tests de los helpers asíncronos y del ``/health`` de ``api-gateway``.

``log_search`` y ``log_audit`` registran en el log-service vía httpx de forma no
bloqueante; aquí se simula httpx para cubrir tanto el camino correcto como la
degradación ante fallos. ``/health`` consulta backend y LLM, también simulados.
"""
import asyncio

from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response

    async def post(self, *args, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


# ----------------------------------------------------------------------------
# log_search / log_audit (no deben lanzar)
# ----------------------------------------------------------------------------
def test_log_search_success(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient(_FakeResp({})))
    asyncio.run(main.log_search(session_id="s", user_id="u", query="q"))


def test_log_search_swallows_errors(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient(raises=RuntimeError("down")))
    asyncio.run(main.log_search(session_id="s", user_id="u", query="q"))


def test_log_audit_success(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient(_FakeResp({})))
    asyncio.run(main.log_audit(session_id="s", user_id="u", records_count=3))


def test_log_audit_swallows_errors(monkeypatch):
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeAsyncClient(raises=RuntimeError("down")))
    asyncio.run(main.log_audit(session_id="s", user_id="u", records_count=3))


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------
def test_health_all_up(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "AsyncClient", _FakeAsyncClient(_FakeResp({"status": "healthy"}))
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["gateway"] == "healthy"
    assert body["backend"] == {"status": "healthy"}


def test_health_backend_down_returns_503(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "AsyncClient", _FakeAsyncClient(raises=RuntimeError("backend caido"))
    )
    resp = client.get("/health")
    assert resp.status_code == 503
