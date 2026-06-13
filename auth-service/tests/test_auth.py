"""Tests unitarios de las funciones de ``auth-service/main.py``.

Cubren la creación/validación de JWT, el hash/verificación de contraseñas con
bcrypt, la extracción de la IP del cliente y el saneado de datos públicos del
usuario. No requieren MongoDB (la conexión se simula como no disponible).
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

import main


# ----------------------------------------------------------------------------
# JWT
# ----------------------------------------------------------------------------
def test_create_and_verify_token_roundtrip():
    token, exp = main.create_token("alice")
    assert isinstance(token, str)
    assert isinstance(exp, datetime)
    payload = main.verify_token(token)
    assert payload["username"] == "alice"


def test_verify_token_invalid_raises_401():
    with pytest.raises(HTTPException) as exc:
        main.verify_token("not-a-real-token")
    assert exc.value.status_code == 401


def test_verify_token_expired_raises_401():
    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jwt.encode(
        {"username": "bob", "exp": expired}, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token(token)
    assert exc.value.status_code == 401


# ----------------------------------------------------------------------------
# Contraseñas (bcrypt)
# ----------------------------------------------------------------------------
def test_hash_and_verify_password():
    hashed = main.hash_password("S3cret!")
    assert hashed != "S3cret!"
    assert main.verify_password("S3cret!", hashed) is True
    assert main.verify_password("incorrecta", hashed) is False


# ----------------------------------------------------------------------------
# get_user_data
# ----------------------------------------------------------------------------
def test_get_user_data_extracts_public_fields():
    user = {
        "_id": 123,
        "username": "alice",
        "admin": True,
        "audit": False,
        "password": "secreto",
    }
    data = main.get_user_data(user)
    assert data == {"user_id": "123", "username": "alice", "admin": True, "audit": False}
    assert "password" not in data


# ----------------------------------------------------------------------------
# get_request_ip
# ----------------------------------------------------------------------------
class _FakeRequest:
    def __init__(self, headers, client_host=None):
        self.headers = headers
        self.client = type("Client", (), {"host": client_host})() if client_host else None


def test_get_request_ip_forwarded_for_takes_first():
    req = _FakeRequest({"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
    assert main.get_request_ip(req) == "203.0.113.5"


def test_get_request_ip_real_ip():
    req = _FakeRequest({"x-real-ip": "203.0.113.9"})
    assert main.get_request_ip(req) == "203.0.113.9"


def test_get_request_ip_socket_fallback():
    req = _FakeRequest({}, client_host="192.168.1.10")
    assert main.get_request_ip(req) == "192.168.1.10"


def test_get_request_ip_unknown():
    req = _FakeRequest({})
    assert main.get_request_ip(req) == "unknown"
