"""Tests unitarios de las funciones de ``history-service/main.py``.

Cubren la verificación de tokens JWT y la extracción del usuario a partir de la
cabecera ``Authorization``.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

import main


def _token(username="alice"):
    payload = {
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)


def test_verify_token_valid():
    payload = main.verify_token(_token("alice"))
    assert payload["username"] == "alice"


def test_verify_token_expired():
    token = jwt.encode(
        {"username": "a", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        main.JWT_SECRET,
        algorithm=main.JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        main.verify_token(token)
    assert exc.value.status_code == 401


def test_verify_token_invalid():
    with pytest.raises(HTTPException) as exc:
        main.verify_token("nope")
    assert exc.value.status_code == 401


def test_get_user_from_token_valid():
    assert main.get_user_from_token(f"Bearer {_token('carol')}") == "carol"


def test_get_user_from_token_missing_header():
    with pytest.raises(HTTPException) as exc:
        main.get_user_from_token(None)
    assert exc.value.status_code == 401


def test_get_user_from_token_bad_scheme():
    with pytest.raises(HTTPException) as exc:
        main.get_user_from_token(f"Basic {_token('x')}")
    assert exc.value.status_code == 401


def test_get_user_from_token_malformed():
    with pytest.raises(HTTPException) as exc:
        main.get_user_from_token("BearerSoloUnToken")
    assert exc.value.status_code == 401
