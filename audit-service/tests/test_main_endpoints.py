"""Tests de ``verify_token`` y del endpoint ``/health`` de ``audit-service/main.py``.

``verify_token`` delega la validación en el API Gateway mediante httpx; aquí se
simula esa llamada.
"""
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------
def test_health():
    data = client.get("/health").json()
    assert data["status"] == "healthy"
    assert data["service"] == "audit-service"


# ----------------------------------------------------------------------------
# verify_token
# ----------------------------------------------------------------------------
def test_verify_token_missing_header():
    with pytest.raises(HTTPException) as exc:
        main.verify_token(None)
    assert exc.value.status_code == 401


def test_verify_token_bad_scheme():
    with pytest.raises(HTTPException) as exc:
        main.verify_token("Basic abc")
    assert exc.value.status_code == 401


def test_verify_token_malformed():
    with pytest.raises(HTTPException) as exc:
        main.verify_token("soloUnToken")
    assert exc.value.status_code == 401


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClientCtx:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


def test_verify_token_valid(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "Client", lambda *a, **k: _FakeClientCtx(_FakeResp(200, {"valid": True, "email": "u@x.com"}))
    )
    assert main.verify_token("Bearer good-token") == "u@x.com"


def test_verify_token_rejected(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "Client", lambda *a, **k: _FakeClientCtx(_FakeResp(200, {"valid": False}))
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token("Bearer bad")
    assert exc.value.status_code == 401


def test_verify_token_non_200(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "Client", lambda *a, **k: _FakeClientCtx(_FakeResp(500, {}))
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token("Bearer x")
    assert exc.value.status_code == 401


def test_verify_token_service_unavailable(monkeypatch):
    monkeypatch.setattr(
        main.httpx, "Client", lambda *a, **k: _FakeClientCtx(raises=httpx.RequestError("down"))
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token("Bearer x")
    assert exc.value.status_code == 500
