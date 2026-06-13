"""Tests de las funciones de acceso a datos de ``auth-service/main.py``.

Se prueban tanto las ramas sin base de datos (``users_collection is None``, el
estado real en los tests) como los caminos correctos inyectando una colección
de MongoDB falsa en memoria. Un fixture guarda y restaura el global para no
contaminar otros tests.
"""
import copy
from datetime import datetime, timezone

import pytest

import main


# ----------------------------------------------------------------------------
# Doble de colección MongoDB
# ----------------------------------------------------------------------------
class _Result:
    def __init__(self, inserted_id=None, modified_count=0, matched_count=0, deleted_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.matched_count = matched_count
        self.deleted_count = deleted_count


def _match(doc, query):
    return all(doc.get(k) == v for k, v in query.items())


class FakeCollection:
    def __init__(self):
        self._docs = []
        self._counter = 0

    def insert_one(self, doc):
        self._counter += 1
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", self._counter)
        self._docs.append(stored)
        return _Result(inserted_id=stored["_id"])

    def find_one(self, query, projection=None):
        for doc in self._docs:
            if _match(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [copy.deepcopy(d) for d in self._docs if _match(d, query)]
        if projection:
            excluded = {k for k, v in projection.items() if v == 0}
            for d in docs:
                for key in excluded:
                    d.pop(key, None)
        return docs

    def update_one(self, query, update):
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                return _Result(modified_count=1, matched_count=1)
        return _Result(modified_count=0, matched_count=0)

    def delete_many(self, query):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not _match(d, query)]
        return _Result(deleted_count=before - len(self._docs))


@pytest.fixture
def users_db():
    """Inyecta una colección falsa en ``main.users_collection`` y la restaura."""
    original = main.users_collection
    fake = FakeCollection()
    main.users_collection = fake
    yield fake
    main.users_collection = original


@pytest.fixture
def no_db():
    """Fuerza ``users_collection = None`` (sin base de datos) y lo restaura."""
    original = main.users_collection
    main.users_collection = None
    yield
    main.users_collection = original


# ----------------------------------------------------------------------------
# Ramas sin base de datos
# ----------------------------------------------------------------------------
def test_get_user_by_username_no_db(no_db):
    assert main.get_user_by_username("x") is None


def test_create_user_no_db(no_db):
    assert main.create_user("x", "p") is False


def test_get_all_users_no_db(no_db):
    assert main.get_all_users() == []


def test_update_user_roles_no_db(no_db):
    assert main.update_user_roles("x", True, False) is False


def test_update_user_password_no_db(no_db):
    assert main.update_user_password("x", "p") is False


# ----------------------------------------------------------------------------
# Caminos correctos con colección inyectada
# ----------------------------------------------------------------------------
def test_create_and_get_user(users_db):
    assert main.create_user("alice", "secret", admin=True) is True
    user = main.get_user_by_username("alice")
    assert user["username"] == "alice"
    assert user["admin"] is True
    # La contraseña se guarda hasheada, no en claro.
    assert user["password"] != "secret"


def test_create_duplicate_user_returns_false(users_db):
    assert main.create_user("bob", "p") is True
    assert main.create_user("bob", "p") is False


def test_get_all_users_strips_password(users_db):
    users_db.insert_one(
        {"username": "carol", "password": "h", "admin": False, "audit": True,
         "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}
    )
    users = main.get_all_users()
    assert len(users) == 1
    assert "password" not in users[0]
    assert isinstance(users[0]["_id"], str)
    assert users[0]["created_at"].startswith("2025-01-01")


def test_update_user_roles_existing(users_db):
    main.create_user("dave", "p")
    assert main.update_user_roles("dave", admin=True, audit=True) is True
    assert main.get_user_by_username("dave")["admin"] is True


def test_update_user_password_existing(users_db):
    main.create_user("erin", "old")
    assert main.update_user_password("erin", "new") is True
    assert main.verify_password("new", main.get_user_by_username("erin")["password"]) is True
