"""Tests de los endpoints de LISTADO y trazabilidad del ``log-service``.

Inyecta colecciones MongoDB falsas (con cursor ``find().sort().skip().limit()``)
para cubrir los GET de sesiones/búsquedas/auditorías/acciones de admin, el
registro de acciones de administración y la actualización del análisis de IA.
"""
import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main


class _Result:
    def __init__(self, inserted_id=None, modified_count=0, matched_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.matched_count = matched_count


def _match(doc, query):
    return all(doc.get(k) == v for k, v in query.items())


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self):
        self._docs = []
        self._counter = 0

    def insert_one(self, doc):
        self._counter += 1
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", f"oid{self._counter}")
        self._docs.append(stored)
        return _Result(inserted_id=stored["_id"])

    def find_one(self, query, sort=None):
        for doc in self._docs:
            if _match(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query=None):
        docs = [copy.deepcopy(d) for d in self._docs if not query or _match(d, query)]
        return FakeCursor(docs)

    def update_one(self, query, update):
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                return _Result(modified_count=1, matched_count=1)
        return _Result()

    def count_documents(self, query):
        return sum(1 for d in self._docs if not query or _match(d, query))


@pytest.fixture
def cols():
    originals = (
        main.sessions_collection, main.searches_collection,
        main.audits_collection, main.admin_actions_collection,
    )
    sessions, searches, audits, admin = (
        FakeCollection(), FakeCollection(), FakeCollection(), FakeCollection(),
    )
    main.sessions_collection = sessions
    main.searches_collection = searches
    main.audits_collection = audits
    main.admin_actions_collection = admin
    yield sessions, searches, audits, admin
    (
        main.sessions_collection, main.searches_collection,
        main.audits_collection, main.admin_actions_collection,
    ) = originals


@pytest.fixture
def client(cols):
    return TestClient(main.app)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------
def test_get_sessions_returns_list(cols, client):
    sessions = cols[0]
    sessions.insert_one({
        "session_id": "s1", "user_id": "u1", "created_at": _now(),
        "closed_at": _now(), "duration_seconds": 12,
        "ip_address": "1.1.1.1", "user_agent": "ua",
    })
    sessions.insert_one({"session_id": "s2", "user_id": "u2", "created_at": _now()})
    body = client.get("/sessions").json()
    assert body["total"] == 2
    assert {s["session_id"] for s in body["sessions"]} == {"s1", "s2"}


def test_get_sessions_filter_by_username(cols, client):
    cols[0].insert_one({
        "session_id": "s1", "user_id": "u1", "created_at": _now(), "username": "alice",
    })
    body = client.get("/sessions", params={"username": "alice"}).json()
    assert body["total"] == 1


# ---------------------------------------------------------------------------
# GET /searches
# ---------------------------------------------------------------------------
def test_get_searches_returns_list(cols, client):
    cols[1].insert_one({
        "session_id": "s1", "user_id": "u1", "query": "tos", "timestamp": _now(),
        "status": "success",
    })
    body = client.get("/searches", params={"user_id": "u1"}).json()
    assert body["total"] == 1
    assert body["searches"][0]["query"] == "tos"


# ---------------------------------------------------------------------------
# GET /audits
# ---------------------------------------------------------------------------
def test_get_audits_returns_list(cols, client):
    cols[2].insert_one({
        "session_id": "s1", "user_id": "u1", "records_count": 3, "timestamp": _now(),
        "status": "success",
    })
    body = client.get("/audits", params={"session_id": "s1"}).json()
    assert body["total"] == 1
    assert body["audits"][0]["records_count"] == 3


# ---------------------------------------------------------------------------
# POST y GET /admin-actions
# ---------------------------------------------------------------------------
def test_register_admin_action_success(cols, client):
    resp = client.post("/admin-actions", json={
        "action": "create_user", "actor_user_id": "admin1",
        "actor_username": "admin", "target_user_id": "u9",
        "target_username": "newbie", "session_id": "s1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["action"] == "create_user"
    assert len(cols[3]._docs) == 1


def test_get_admin_actions_with_filters(cols, client):
    cols[3].insert_one({
        "action_id": "a1", "action": "delete_user", "actor_user_id": "admin1",
        "target_user_id": "u9", "session_id": "s1", "timestamp": _now(),
        "status": "success",
    })
    body = client.get("/admin-actions", params={"action": "delete_user"}).json()
    assert body["total"] == 1
    assert body["actions"][0]["action"] == "delete_user"


def test_get_admin_actions_empty(cols, client):
    body = client.get("/admin-actions").json()
    assert body["total"] == 0
    assert body["actions"] == []


# ---------------------------------------------------------------------------
# PATCH /searches/update-ai
# ---------------------------------------------------------------------------
def test_update_ai_analysis_success(cols, client):
    cols[1].insert_one({
        "session_id": "s1", "user_id": "u1", "query": "tos", "timestamp": _now(),
        "status": "success",
    })
    resp = client.patch("/searches/update-ai", json={
        "session_id": "s1", "query": "tos",
        "ai_analysis": {"diagnosis": "x", "improvement_tips": ["y"]},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_update_ai_analysis_not_found_404(cols, client):
    resp = client.patch("/searches/update-ai", json={
        "session_id": "nope", "query": "nope", "ai_analysis": {},
    })
    assert resp.status_code == 404
