"""Tests de cobertura para ``history-service/main.py``.

Cubren las ramas que el resto de la suite no toca: ``_require_env``,
``init_mongodb`` (éxito y error genérico), ``get_user_from_token`` sin username,
``sanitize_log(None)``, y las ramas de error de los tres endpoints de historial
(sin conexión a MongoDB y excepción interna inesperada).
"""
import copy
from datetime import datetime, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


# ---------------------------------------------------------------------------
# Dobles de MongoDB
# ---------------------------------------------------------------------------
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
        matched = [copy.deepcopy(d) for d in self._docs
                   if all(d.get(k) == v for k, v in query.items())]
        return FakeCursor(matched)

    def count_documents(self, query):
        return sum(1 for d in self._docs if all(d.get(k) == v for k, v in query.items()))


class BoomCollection:
    """Colección cuyo find_one lanza (para las ramas ``except`` genéricas)."""

    def find_one(self, query):
        raise RuntimeError("mongo caído")


class FakeDB:
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections[name]


def _auth(username="alice"):
    token = jwt.encode(
        {"username": username, "exp": datetime.now(timezone.utc).timestamp() + 3600},
        main.JWT_SECRET, algorithm=main.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _restore_globals():
    snap = (main.mongo_client, main.db, main.searches_collection)
    yield
    (main.mongo_client, main.db, main.searches_collection) = snap


# ---------------------------------------------------------------------------
# _require_env
# ---------------------------------------------------------------------------
def test_require_env_missing_raises(monkeypatch):
    monkeypatch.delenv("VAR_QUE_NO_EXISTE", raising=False)
    with pytest.raises(RuntimeError):
        main._require_env("VAR_QUE_NO_EXISTE")


# ---------------------------------------------------------------------------
# init_mongodb
# ---------------------------------------------------------------------------
def test_init_mongodb_success(monkeypatch):
    class FakeColl:
        def create_index(self, *a, **k):
            return None

    class FakeDatabase:
        def __getitem__(self, name):
            return FakeColl()

    class FakeAdmin:
        def command(self, *a, **k):
            return {"ok": 1}

    class FakeClient:
        def __init__(self, *a, **k):
            self.admin = FakeAdmin()

        def get_database(self, name):
            return FakeDatabase()

    monkeypatch.setattr(main, "MongoClient", FakeClient)
    assert main.init_mongodb() is True
    assert main.searches_collection is not None


def test_init_mongodb_generic_error(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise ValueError("uri inválida")

    monkeypatch.setattr(main, "MongoClient", Boom)
    assert main.init_mongodb() is False


# ---------------------------------------------------------------------------
# get_user_from_token / sanitize_log
# ---------------------------------------------------------------------------
def test_get_user_from_token_without_username():
    token = jwt.encode(
        {"exp": datetime.now(timezone.utc).timestamp() + 3600},
        main.JWT_SECRET, algorithm=main.JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        main.get_user_from_token(f"Bearer {token}")
    assert exc.value.status_code == 401


def test_sanitize_log_none_returns_empty():
    assert main.sanitize_log(None) == ""


# ---------------------------------------------------------------------------
# Helpers para inyectar estado
# ---------------------------------------------------------------------------
def _set(searches_docs):
    users = FakeCollection([{"_id": "user-1", "username": "alice"}])
    main.searches_collection = FakeCollection(searches_docs)
    main.db = FakeDB({"users": users})


def _set_boom():
    main.searches_collection = FakeCollection([])
    main.db = FakeDB({"users": BoomCollection()})


# ---------------------------------------------------------------------------
# /history — sin BD, timestamp naive, y excepción interna
# ---------------------------------------------------------------------------
def test_history_no_db_returns_500():
    main.searches_collection = None
    assert client.get("/history", headers=_auth()).status_code == 500


def test_history_naive_timestamp_is_handled():
    naive = datetime.now()  # noqa: DTZ005 (intencionado: sin tzinfo)
    _set([{"_id": "s1", "user_id": "user-1", "query": "x", "timestamp": naive}])
    resp = client.get("/history", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_history_internal_error_returns_500():
    _set_boom()
    assert client.get("/history", headers=_auth()).status_code == 500


# ---------------------------------------------------------------------------
# /history/count — sin BD y excepción interna
# ---------------------------------------------------------------------------
def test_history_count_no_db_returns_500():
    main.searches_collection = None
    assert client.get("/history/count", headers=_auth()).status_code == 500


def test_history_count_internal_error_returns_500():
    _set_boom()
    assert client.get("/history/count", headers=_auth()).status_code == 500


# ---------------------------------------------------------------------------
# /history/recent — sin BD y excepción interna
# ---------------------------------------------------------------------------
def test_history_recent_no_db_returns_500():
    main.searches_collection = None
    assert client.get("/history/recent", headers=_auth()).status_code == 500


def test_history_recent_internal_error_returns_500():
    _set_boom()
    assert client.get("/history/recent", headers=_auth()).status_code == 500
