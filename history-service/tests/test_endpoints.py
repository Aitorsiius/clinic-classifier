"""Tests del endpoint ``/history`` y ``/health`` de ``history-service/main.py``.

Se inyectan una colección de búsquedas y una base de datos falsas (con la
colección ``users``) para ejercitar la segmentación temporal del historial sin
MongoDB real. La autenticación se hace con un JWT válido firmado con el secreto
de test.
"""
import copy
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import main


# ----------------------------------------------------------------------------
# Dobles de MongoDB
# ----------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=-1):
        self._docs.sort(key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or []

    def find_one(self, query):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return copy.deepcopy(doc)
        return None

    def find(self, query):
        matched = [
            copy.deepcopy(d)
            for d in self._docs
            if all(d.get(k) == v for k, v in query.items())
        ]
        return FakeCursor(matched)


class FakeDB:
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections[name]


def _token(username="alice"):
    payload = {
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)


def _auth_header(username="alice"):
    return {"Authorization": f"Bearer {_token(username)}"}


@pytest.fixture
def history_env():
    """Inyecta ``searches_collection`` y ``db`` falsos; los restaura al terminar."""
    original_searches = main.searches_collection
    original_db = main.db
    yield
    main.searches_collection = original_searches
    main.db = original_db


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------
def test_health_ok(history_env):
    main.searches_collection = FakeCollection()
    assert TestClient(main.app).get("/health").json()["status"] == "ok"


def test_health_error_without_db(history_env):
    main.searches_collection = None
    assert TestClient(main.app).get("/health").json()["status"] == "error"


# ----------------------------------------------------------------------------
# /history
# ----------------------------------------------------------------------------
def test_history_requires_auth(history_env):
    main.searches_collection = FakeCollection()
    main.db = FakeDB({"users": FakeCollection()})
    assert TestClient(main.app).get("/history").status_code == 401


def test_history_user_not_found_returns_empty(history_env):
    main.searches_collection = FakeCollection()
    main.db = FakeDB({"users": FakeCollection()})  # sin usuarios
    resp = TestClient(main.app).get("/history", headers=_auth_header())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["history"]["last_hour"] == []


def test_history_segments_recent_search(history_env):
    users = FakeCollection([{"_id": "user-1", "username": "alice"}])
    now = datetime.now(timezone.utc)
    searches = FakeCollection(
        [
            {
                "_id": "search-1",
                "search_id": "search-1",
                "user_id": "user-1",
                "query": "tos persistente",
                "timestamp": now,
                "results_count": 2,
                "status": "success",
            }
        ]
    )
    main.searches_collection = searches
    main.db = FakeDB({"users": users})

    resp = TestClient(main.app).get("/history", headers=_auth_header("alice"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["history"]["last_hour"]) == 1
    assert body["history"]["last_hour"][0]["query"] == "tos persistente"
