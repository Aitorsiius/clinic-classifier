"""Tests de endpoints y helpers de ``log-service/main.py``.

Se inyectan colecciones de MongoDB falsas en memoria en los globales del módulo
para ejercitar ``serialize_doc``, las consultas de sesión y los endpoints de
creación/cierre de sesión y registro de búsquedas/auditorías con ``TestClient``.
"""
import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main


# ----------------------------------------------------------------------------
# Doble de colección MongoDB
# ----------------------------------------------------------------------------
class _Result:
    def __init__(self, inserted_id=None, modified_count=0, matched_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.matched_count = matched_count


def _match(doc, query):
    for k, v in query.items():
        if doc.get(k) != v:
            return False
    return True


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

    def find_one(self, query):
        for doc in self._docs:
            if _match(doc, query):
                return copy.deepcopy(doc)
        return None

    def update_one(self, query, update):
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                return _Result(modified_count=1, matched_count=1)
        return _Result(modified_count=0, matched_count=0)

    def count_documents(self, query):
        return sum(1 for d in self._docs if _match(d, query))


@pytest.fixture
def collections():
    """Inyecta colecciones falsas y las restaura tras el test."""
    originals = (
        main.sessions_collection,
        main.searches_collection,
        main.audits_collection,
    )
    sessions, searches, audits = FakeCollection(), FakeCollection(), FakeCollection()
    main.sessions_collection = sessions
    main.searches_collection = searches
    main.audits_collection = audits
    yield sessions, searches, audits
    (
        main.sessions_collection,
        main.searches_collection,
        main.audits_collection,
    ) = originals


@pytest.fixture
def client(collections):
    return TestClient(main.app)


# ----------------------------------------------------------------------------
# serialize_doc
# ----------------------------------------------------------------------------
def test_serialize_doc_none():
    assert main.serialize_doc(None) is None


def test_serialize_doc_stringifies_id():
    doc = main.serialize_doc({"_id": 123, "x": 1})
    assert doc["_id"] == "123"


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------
def test_health_ok(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"


def test_health_error_without_db():
    original = main.sessions_collection
    main.sessions_collection = None
    try:
        data = TestClient(main.app).get("/health").json()
        assert data["status"] == "error"
    finally:
        main.sessions_collection = original


# ----------------------------------------------------------------------------
# Sesiones
# ----------------------------------------------------------------------------
def test_create_session(client):
    resp = client.post("/sessions/create", json={"user_id": "u1", "ip_address": "1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u1"
    assert body["session_id"]


def test_close_session_success(client, collections):
    sessions, _, _ = collections
    create = client.post("/sessions/create", json={"user_id": "u1"})
    session_id = create.json()["session_id"]
    resp = client.post("/sessions/close", json={"session_id": session_id})
    assert resp.status_code == 200
    assert resp.json()["duration_seconds"] >= 0


def test_close_session_not_found(client):
    resp = client.post("/sessions/close", json={"session_id": "inexistente"})
    assert resp.status_code == 404


def test_close_session_already_closed(client, collections):
    sessions, _, _ = collections
    create = client.post("/sessions/create", json={"user_id": "u1"})
    session_id = create.json()["session_id"]
    client.post("/sessions/close", json={"session_id": session_id})
    resp = client.post("/sessions/close", json={"session_id": session_id})
    assert resp.status_code == 400


# ----------------------------------------------------------------------------
# get_session_by_id / get_session_by_user_id_active
# ----------------------------------------------------------------------------
def test_get_session_helpers(client, collections):
    sessions, _, _ = collections
    create = client.post("/sessions/create", json={"user_id": "u9"})
    session_id = create.json()["session_id"]
    assert main.get_session_by_id(session_id)["user_id"] == "u9"
    assert main.get_session_by_user_id_active("u9") is not None


# ----------------------------------------------------------------------------
# Búsquedas y auditorías
# ----------------------------------------------------------------------------
def test_register_search(client):
    resp = client.post(
        "/searches",
        json={"session_id": "s1", "user_id": "u1", "query": "tos", "results_count": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("success", "error")


def test_register_search_without_db():
    original = main.searches_collection
    main.searches_collection = None
    try:
        resp = TestClient(main.app).post(
            "/searches",
            json={"session_id": "s1", "user_id": "u1", "query": "tos", "results_count": 0},
        )
        assert resp.json()["status"] == "error"
    finally:
        main.searches_collection = original


def test_register_audit(client):
    resp = client.post(
        "/audits",
        json={"session_id": "s1", "user_id": "u1", "records_count": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "u1"
