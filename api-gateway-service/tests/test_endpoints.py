"""Tests de endpoints y helpers de ``api-gateway-service/main.py``.

Cubren ``get_current_user``, ``get_client_ip`` y los endpoints que no dependen
de otros microservicios (``/``, ``/api/verify-token``, ``/auth/verify``).
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


# ----------------------------------------------------------------------------
# get_current_user
# ----------------------------------------------------------------------------
class _Req:
    def __init__(self, headers):
        self.headers = headers


def test_get_current_user_valid():
    token = main.create_token("alice")
    assert main.get_current_user(_Req({"Authorization": f"Bearer {token}"})) == "alice"


def test_get_current_user_missing_header():
    with pytest.raises(HTTPException) as exc:
        main.get_current_user(_Req({}))
    assert exc.value.status_code == 401


def test_get_current_user_bad_scheme():
    token = main.create_token("alice")
    with pytest.raises(HTTPException) as exc:
        main.get_current_user(_Req({"Authorization": f"Basic {token}"}))
    assert exc.value.status_code == 401


def test_get_current_user_malformed():
    with pytest.raises(HTTPException) as exc:
        main.get_current_user(_Req({"Authorization": "soloUnToken"}))
    assert exc.value.status_code == 401


# ----------------------------------------------------------------------------
# get_client_ip
# ----------------------------------------------------------------------------
def test_get_client_ip_with_client():
    req = type("R", (), {"client": type("C", (), {"host": "10.0.0.5"})()})()
    assert main.get_client_ip(req) == "10.0.0.5"


def test_get_client_ip_without_client():
    req = type("R", (), {"client": None})()
    assert main.get_client_ip(req) == "unknown"


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------
def test_root():
    data = client.get("/").json()
    assert data["service"].startswith("API Gateway")
    assert data["status"] == "running"


def test_verify_token_endpoint_valid():
    token = main.create_token("carol")
    resp = client.get("/api/verify-token", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"username": "carol", "status": "valid"}


def test_verify_token_endpoint_missing_auth():
    assert client.get("/api/verify-token").status_code == 401


def test_auth_verify_valid_token():
    token = main.create_token("dave")
    resp = client.post("/auth/verify", json={"token": token})
    body = resp.json()
    assert body["valid"] is True
    assert body["username"] == "dave"


def test_auth_verify_invalid_token():
    resp = client.post("/auth/verify", json={"token": "no-valido"})
    assert resp.json() == {"valid": False, "detail": "Invalid token"}


def test_auth_verify_missing_token():
    resp = client.post("/auth/verify", json={})
    assert resp.status_code == 400
