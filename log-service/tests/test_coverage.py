"""Tests de cobertura para ``log-service/main.py``.

Ejercitan las ramas de error que el resto de la suite no toca: inicialización
de MongoDB (éxito y fallo genérico), helpers de sesión sin conexión o con
excepción, y todos los endpoints ante colecciones ausentes, inserciones
fallidas y excepciones internas. También cubren los filtros de query que
faltaban en los endpoints de listado.
"""
import copy
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main


# ---------------------------------------------------------------------------
# Dobles de colección MongoDB
# ---------------------------------------------------------------------------
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
    """Colección en memoria. ``insert_result_id`` permite simular un fallo de
    inserción (``None`` -> ``result.inserted_id`` falsy)."""

    def __init__(self):
        self._docs = []
        self._counter = 0
        self.insert_result_id = "auto"

    def insert_one(self, doc):
        self._counter += 1
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", f"oid{self._counter}")
        self._docs.append(stored)
        if self.insert_result_id == "auto":
            return _Result(inserted_id=stored["_id"])
        return _Result(inserted_id=self.insert_result_id)

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


class ZeroUpdateCollection(FakeCollection):
    """find_one encuentra el documento, pero update_one no casa ninguno."""

    def update_one(self, query, update):
        return _Result(modified_count=0, matched_count=0)


class BoomCollection:
    """Toda operación lanza excepción (para cubrir los bloques ``except``)."""

    def insert_one(self, doc):
        raise RuntimeError("boom")

    def find_one(self, query, sort=None):
        raise RuntimeError("boom")

    def find(self, query=None):
        raise RuntimeError("boom")

    def update_one(self, query, update):
        raise RuntimeError("boom")

    def count_documents(self, query):
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _restore_globals():
    """Restaura los globales de conexión tras cada test (los tests reasignan
    ``main.<collection>`` directamente para simular estados de error)."""
    snap = (
        main.mongo_client, main.db,
        main.sessions_collection, main.searches_collection,
        main.audits_collection, main.admin_actions_collection,
    )
    yield
    (
        main.mongo_client, main.db,
        main.sessions_collection, main.searches_collection,
        main.audits_collection, main.admin_actions_collection,
    ) = snap


@pytest.fixture
def cols():
    """Inyecta colecciones falsas frescas en los cuatro globales."""
    sessions, searches, audits, admin = (
        FakeCollection(), FakeCollection(), FakeCollection(), FakeCollection(),
    )
    main.sessions_collection = sessions
    main.searches_collection = searches
    main.audits_collection = audits
    main.admin_actions_collection = admin
    return sessions, searches, audits, admin


def _client():
    return TestClient(main.app)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# init_mongodb
# ---------------------------------------------------------------------------
def test_init_mongodb_success(monkeypatch):
    class FakeColl:
        def create_index(self, *a, **k):
            return None

    class FakeDB:
        def __getitem__(self, name):
            return FakeColl()

    class FakeAdmin:
        def command(self, *a, **k):
            return {"ok": 1}

    class FakeClient:
        def __init__(self, *a, **k):
            self.admin = FakeAdmin()

        def get_database(self, name):
            return FakeDB()

    monkeypatch.setattr(main, "MongoClient", FakeClient)
    assert main.init_mongodb() is True
    assert main.sessions_collection is not None
    assert main.admin_actions_collection is not None


def test_init_mongodb_generic_error(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise ValueError("uri inválida")

    monkeypatch.setattr(main, "MongoClient", Boom)
    assert main.init_mongodb() is False


# ---------------------------------------------------------------------------
# get_session_by_id / get_session_by_user_id_active
# ---------------------------------------------------------------------------
def test_get_session_by_id_no_collection():
    main.sessions_collection = None
    assert main.get_session_by_id("x") is None


def test_get_session_by_id_exception():
    main.sessions_collection = BoomCollection()
    assert main.get_session_by_id("x") is None


def test_get_session_active_no_collection():
    main.sessions_collection = None
    assert main.get_session_by_user_id_active("u") is None


def test_get_session_active_exception():
    main.sessions_collection = BoomCollection()
    assert main.get_session_by_user_id_active("u") is None


# ---------------------------------------------------------------------------
# sanitize_log
# ---------------------------------------------------------------------------
def test_sanitize_log_none_returns_empty():
    assert main.sanitize_log(None) == ""


def test_sanitize_log_strips_crlf():
    assert main.sanitize_log("a\r\nb") == "a  b"


# ---------------------------------------------------------------------------
# /sessions/create
# ---------------------------------------------------------------------------
def test_create_session_no_db():
    main.sessions_collection = None
    resp = _client().post("/sessions/create", json={"user_id": "u"})
    assert resp.status_code == 500


def test_create_session_insert_fails():
    c = FakeCollection()
    c.insert_result_id = None
    main.sessions_collection = c
    resp = _client().post("/sessions/create", json={"user_id": "u"})
    assert resp.status_code == 500


def test_create_session_exception():
    main.sessions_collection = BoomCollection()
    resp = _client().post("/sessions/create", json={"user_id": "u"})
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /sessions/close
# ---------------------------------------------------------------------------
def test_close_session_no_db():
    main.sessions_collection = None
    resp = _client().post("/sessions/close", json={"session_id": "s"})
    assert resp.status_code == 500


def test_close_session_naive_created_at(cols):
    cols[0].insert_one({
        "session_id": "s", "user_id": "u",
        "created_at": datetime(2020, 1, 1), "closed_at": None,
    })
    resp = _client().post("/sessions/close", json={"session_id": "s"})
    assert resp.status_code == 200
    assert resp.json()["duration_seconds"] >= 0


def test_close_session_update_no_match():
    c = ZeroUpdateCollection()
    c.insert_one({
        "session_id": "s", "user_id": "u",
        "created_at": _now(), "closed_at": None,
    })
    main.sessions_collection = c
    resp = _client().post("/sessions/close", json={"session_id": "s"})
    assert resp.status_code == 404


def test_close_session_exception():
    class BoomUpdate(FakeCollection):
        def update_one(self, query, update):
            raise RuntimeError("boom")

    c = BoomUpdate()
    c.insert_one({
        "session_id": "s", "user_id": "u",
        "created_at": _now(), "closed_at": None,
    })
    main.sessions_collection = c
    resp = _client().post("/sessions/close", json={"session_id": "s"})
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /searches
# ---------------------------------------------------------------------------
def test_register_search_insert_fails(cols):
    cols[1].insert_result_id = None
    resp = _client().post(
        "/searches", json={"session_id": "s", "user_id": "u", "query": "q"}
    )
    assert resp.json()["status"] == "error"


def test_register_search_exception(cols):
    main.searches_collection = BoomCollection()
    resp = _client().post(
        "/searches", json={"session_id": "s", "user_id": "u", "query": "q"}
    )
    assert resp.json()["status"] == "error"


def test_register_search_with_existing_session(cols):
    cols[0].insert_one({
        "session_id": "s1", "user_id": "u", "created_at": _now(), "closed_at": None,
    })
    resp = _client().post(
        "/searches",
        json={"session_id": "s1", "user_id": "u", "query": "q", "results_count": 1},
    )
    assert resp.json()["status"] == "success"


# ---------------------------------------------------------------------------
# PATCH /searches/update-ai
# ---------------------------------------------------------------------------
def test_update_ai_no_db():
    main.searches_collection = None
    resp = _client().patch(
        "/searches/update-ai",
        json={"session_id": "s", "query": "q", "ai_analysis": {}},
    )
    assert resp.status_code == 500


def test_update_ai_update_no_match():
    c = ZeroUpdateCollection()
    c.insert_one({"session_id": "s", "query": "q", "timestamp": _now()})
    main.searches_collection = c
    resp = _client().patch(
        "/searches/update-ai",
        json={"session_id": "s", "query": "q", "ai_analysis": {}},
    )
    assert resp.status_code == 404


def test_update_ai_exception():
    main.searches_collection = BoomCollection()
    resp = _client().patch(
        "/searches/update-ai",
        json={"session_id": "s", "query": "q", "ai_analysis": {}},
    )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /audits
# ---------------------------------------------------------------------------
def test_register_audit_no_db():
    main.audits_collection = None
    resp = _client().post(
        "/audits", json={"session_id": "s", "user_id": "u", "records_count": 1}
    )
    assert resp.json()["status"] == "error"


def test_register_audit_insert_fails(cols):
    cols[2].insert_result_id = None
    resp = _client().post(
        "/audits", json={"session_id": "s", "user_id": "u", "records_count": 1}
    )
    body = resp.json()
    assert body["status"] == "error"
    assert body["user_id"] == "u"


def test_register_audit_exception(cols):
    main.audits_collection = BoomCollection()
    resp = _client().post(
        "/audits", json={"session_id": "s", "user_id": "u", "records_count": 1}
    )
    assert resp.json()["status"] == "error"


def test_register_audit_with_existing_session(cols):
    cols[0].insert_one({
        "session_id": "s1", "user_id": "u", "created_at": _now(), "closed_at": None,
    })
    resp = _client().post(
        "/audits", json={"session_id": "s1", "user_id": "u", "records_count": 2}
    )
    assert resp.json()["status"] == "success"


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------
def test_get_sessions_no_db():
    main.sessions_collection = None
    assert _client().get("/sessions").status_code == 500


def test_get_sessions_exception():
    main.sessions_collection = BoomCollection()
    assert _client().get("/sessions").status_code == 500


# ---------------------------------------------------------------------------
# GET /searches
# ---------------------------------------------------------------------------
def test_get_searches_filter_by_session(cols):
    cols[1].insert_one({
        "session_id": "s1", "user_id": "u1", "query": "q", "timestamp": _now(),
    })
    body = _client().get("/searches", params={"session_id": "s1"}).json()
    assert body["total"] == 1


def test_get_searches_no_db():
    main.searches_collection = None
    assert _client().get("/searches").status_code == 500


def test_get_searches_exception():
    main.searches_collection = BoomCollection()
    assert _client().get("/searches").status_code == 500


# ---------------------------------------------------------------------------
# GET /audits
# ---------------------------------------------------------------------------
def test_get_audits_filter_by_user(cols):
    cols[2].insert_one({
        "session_id": "s", "user_id": "u1", "records_count": 1, "timestamp": _now(),
    })
    body = _client().get("/audits", params={"user_id": "u1"}).json()
    assert body["total"] == 1


def test_get_audits_no_db():
    main.audits_collection = None
    assert _client().get("/audits").status_code == 500


def test_get_audits_exception():
    main.audits_collection = BoomCollection()
    assert _client().get("/audits").status_code == 500


# ---------------------------------------------------------------------------
# POST /admin-actions
# ---------------------------------------------------------------------------
def test_register_admin_action_no_db():
    main.admin_actions_collection = None
    resp = _client().post(
        "/admin-actions", json={"action": "create_user", "actor_user_id": "a"}
    )
    assert resp.json()["status"] == "error"


def test_register_admin_action_insert_fails(cols):
    cols[3].insert_result_id = None
    resp = _client().post(
        "/admin-actions", json={"action": "create_user", "actor_user_id": "a"}
    )
    assert resp.json()["status"] == "error"


def test_register_admin_action_exception():
    main.admin_actions_collection = BoomCollection()
    resp = _client().post(
        "/admin-actions", json={"action": "create_user", "actor_user_id": "a"}
    )
    assert resp.json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /admin-actions
# ---------------------------------------------------------------------------
def test_get_admin_actions_all_filters(cols):
    cols[3].insert_one({
        "action": "delete_user", "actor_user_id": "a", "target_user_id": "t",
        "session_id": "s", "timestamp": _now(),
    })
    body = _client().get(
        "/admin-actions",
        params={"session_id": "s", "actor_user_id": "a", "target_user_id": "t"},
    ).json()
    assert body["total"] == 1


def test_get_admin_actions_doc_without_timestamp(cols):
    cols[3].insert_one({"action": "create_user", "actor_user_id": "a"})
    body = _client().get("/admin-actions").json()
    assert body["total"] == 1
    assert body["actions"][0]["action"] == "create_user"


def test_get_admin_actions_no_db():
    main.admin_actions_collection = None
    assert _client().get("/admin-actions").status_code == 500


def test_get_admin_actions_exception():
    main.admin_actions_collection = BoomCollection()
    assert _client().get("/admin-actions").status_code == 500
