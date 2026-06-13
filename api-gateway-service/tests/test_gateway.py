"""Tests unitarios de las funciones de ``api-gateway-service/main.py``.

Cubren la creación y validación de tokens JWT que realiza el gateway.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

import main


def test_create_token_returns_decodable_jwt():
    token = main.create_token("alice")
    assert isinstance(token, str)
    payload = jwt.decode(token, main.JWT_SECRET, algorithms=[main.JWT_ALGORITHM])
    assert payload["username"] == "alice"


def test_verify_token_roundtrip():
    token = main.create_token("bob")
    payload = main.verify_token(token)
    assert payload["username"] == "bob"


def test_verify_token_invalid_raises_401():
    with pytest.raises(HTTPException) as exc:
        main.verify_token("garbage")
    assert exc.value.status_code == 401


def test_verify_token_expired_raises_401():
    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jwt.encode(
        {"username": "x", "exp": expired}, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token(token)
    assert exc.value.status_code == 401


def test_service_app_imports():
    assert hasattr(main, "app")
