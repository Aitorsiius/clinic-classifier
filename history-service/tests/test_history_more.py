"""Tests adicionales de ``history-service``: ``/history/count``,
``/history/recent`` y la segmentación temporal completa de ``/history``.

Reutiliza dobles de MongoDB en memoria (colección de búsquedas + ``db['users']``)
y un JWT válido firmado con el secreto de test.
"""
import copy
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import main


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

    def count_documents(self, query):
        return sum(
            1 for d in self._docs if all(d.get(k) == v for k, v in query.items())
        )


class FakeDB:
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections[name]


def _auth(username="alice"):
    token = jwt.encode(
        {"username": username, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        main.JWT_SECRET, algorithm=main.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env():
    original_searches = main.searches_collection
    original_db = main.db
    yield
    main.searches_collection = original_searches
    main.db = original_db


@pytest.fixture
def client():
    return TestClient(main.app)


def _set(searches_docs, with_user=True):
    users = FakeCollection([{"_id": "user-1", "username": "alice"}] if with_user else [])
    main.searches_collection = FakeCollection(searches_docs)
    main.db = FakeDB({"users": users})


# ---------------------------------------------------------------------------
# /history/count
# ---------------------------------------------------------------------------
def test_count_requires_auth(env, client):
    _set([])
    assert client.get("/history/count").status_code == 401


def test_count_user_not_found_returns_zero(env, client):
    _set([], with_user=False)
    body = client.get("/history/count", headers=_auth()).json()
    assert body["total_searches"] == 0


def test_count_success(env, client):
    _set([
        {"_id": "s1", "user_id": "user-1", "query": "a", "timestamp": datetime.now(timezone.utc)},
        {"_id": "s2", "user_id": "user-1", "query": "b", "timestamp": datetime.now(timezone.utc)},
    ])
    body = client.get("/history/count", headers=_auth()).json()
    assert body["total_searches"] == 2


# ---------------------------------------------------------------------------
# /history/recent
# ---------------------------------------------------------------------------
def test_recent_requires_auth(env, client):
    _set([])
    assert client.get("/history/recent").status_code == 401


def test_recent_user_not_found_empty(env, client):
    _set([], with_user=False)
    body = client.get("/history/recent", headers=_auth()).json()
    assert body["count"] == 0
    assert body["searches"] == []


def test_recent_success(env, client):
    now = datetime.now(timezone.utc)
    _set([
        {"_id": "s1", "search_id": "s1", "user_id": "user-1", "query": "tos",
         "timestamp": now, "results_count": 3, "status": "success"},
    ])
    body = client.get("/history/recent", headers=_auth(), params={"limit": 5}).json()
    assert body["count"] == 1
    assert body["searches"][0]["query"] == "tos"


def test_recent_naive_timestamp_is_handled(env, client):
    # timestamp sin tzinfo -> el endpoint debe asignarle UTC sin fallar.
    naive = datetime.now()  # noqa: DTZ005 (intencionado para la prueba)
    _set([
        {"_id": "s1", "user_id": "user-1", "query": "x", "timestamp": naive},
    ])
    resp = client.get("/history/recent", headers=_auth())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /history: segmentación temporal en todos los tramos
# ---------------------------------------------------------------------------
def test_history_segments_all_buckets(env, client):
    now = datetime.now(timezone.utc)
    docs = [
        {"_id": "h", "user_id": "user-1", "query": "hora", "timestamp": now - timedelta(minutes=10)},
        {"_id": "d", "user_id": "user-1", "query": "dia", "timestamp": now - timedelta(hours=5)},
        {"_id": "w", "user_id": "user-1", "query": "semana", "timestamp": now - timedelta(days=3)},
        {"_id": "m", "user_id": "user-1", "query": "mes", "timestamp": now - timedelta(days=10)},
        {"_id": "y", "user_id": "user-1", "query": "anio", "timestamp": now - timedelta(days=100)},
        {"_id": "o", "user_id": "user-1", "query": "viejo", "timestamp": now - timedelta(days=500)},
    ]
    _set(docs)
    body = client.get("/history", headers=_auth(), params={"limit": 100}).json()
    assert body["total"] == 6
    h = body["history"]
    assert len(h["last_hour"]) == 1
    assert len(h["last_day"]) == 1
    assert len(h["last_week"]) == 1
    assert len(h["last_month"]) == 1
    assert len(h["last_year"]) == 1
    assert len(h["older"]) == 1
