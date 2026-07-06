"""Tests de cobertura para ``auth-service/main.py``.

Cubren las ramas que el resto de la suite no toca: helpers de config/token,
``init_mongodb`` (éxito y error genérico), las ramas ``except`` de las funciones
de acceso a datos, la autorización de admin, y las ramas defensivas 500/503 de
los endpoints de login y administración.
"""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


# ===========================================================================
# Dobles de prueba
# ===========================================================================
class FakeResult:
    def __init__(self, inserted_id=None, modified_count=0, matched_count=0, deleted_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class FakeUsers:
    def __init__(self):
        self._docs = []
        self._next_id = 1

    @staticmethod
    def _match(doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def find_one(self, query, projection=None):
        for d in self._docs:
            if self._match(d, query):
                return dict(d)
        return None

    def find(self, query=None, projection=None):
        out = []
        for d in self._docs:
            if not query or self._match(d, query):
                doc = dict(d)
                if projection and projection.get("password") == 0:
                    doc.pop("password", None)
                out.append(doc)
        return out

    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = self._next_id
        self._next_id += 1
        self._docs.append(doc)
        return FakeResult(inserted_id=doc["_id"])

    def update_one(self, query, update):
        for d in self._docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return FakeResult(modified_count=1, matched_count=1)
        return FakeResult()

    def delete_one(self, query):
        for i, d in enumerate(self._docs):
            if self._match(d, query):
                del self._docs[i]
                return FakeResult(deleted_count=1)
        return FakeResult()


class BoomColl:
    """Colección cuyas operaciones lanzan (para las ramas ``except``)."""

    def find_one(self, *a, **k):
        raise RuntimeError("boom")

    def find(self, *a, **k):
        raise RuntimeError("boom")

    def insert_one(self, *a, **k):
        raise RuntimeError("boom")

    def update_one(self, *a, **k):
        raise RuntimeError("boom")

    def delete_one(self, *a, **k):
        raise RuntimeError("boom")


class FakeLimiter:
    def __init__(self):
        self.blocked_ids = set()

    def is_blocked(self, user_id=None):
        return user_id in self.blocked_ids

    def record_failed_attempt(self, user_id, ip, ua):
        return {"blocked": False}

    def reset_on_success(self, user_id):
        pass

    def get_blocked_user_ids(self):
        return set(self.blocked_ids)

    def delete_user_records(self, user_id):
        pass

    def get_block_info(self, user_id):
        return {"failed_attempts": [], "block_count": 0, "current_block": None}

    def unblock(self, user_id, admin_user_id):
        return True


class _OkHTTP:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def post(self, *a, **k):
        class _R:
            status_code = 200

            def json(self):
                return {}
        return _R()


class _BoomHTTP(_OkHTTP):
    async def post(self, *a, **k):
        raise RuntimeError("log-service caído")


client = TestClient(main.app)


def _admin_headers():
    token, _ = main.create_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(monkeypatch):
    users = FakeUsers()
    users.insert_one({"username": "admin", "password": main.hash_password("admin-pass"),
                      "admin": True, "audit": False})
    users.insert_one({"username": "bob", "password": main.hash_password("bob-pass"),
                      "admin": False, "audit": False})
    limiter = FakeLimiter()
    monkeypatch.setattr(main, "users_collection", users)
    monkeypatch.setattr(main, "rate_limiter", limiter)
    monkeypatch.setattr(main.httpx, "AsyncClient", _OkHTTP)
    return type("Env", (), {"users": users, "limiter": limiter})


# ===========================================================================
# Helpers de configuración / token
# ===========================================================================
def test_sanitize_log_none_and_crlf():
    assert main.sanitize_log(None) == ""
    assert main.sanitize_log("a\r\nb") == "a  b"


def test_require_env_missing_raises(monkeypatch):
    monkeypatch.delenv("VAR_QUE_NO_EXISTE", raising=False)
    with pytest.raises(RuntimeError):
        main._require_env("VAR_QUE_NO_EXISTE")


def test_create_token_with_explicit_hours():
    token, exp = main.create_token("u", hours=1)
    assert isinstance(token, str)


def test_get_user_id_none_without_user(monkeypatch):
    monkeypatch.setattr(main, "users_collection", None)
    monkeypatch.setattr(main, "init_mongodb", lambda: None)
    assert main.get_user_id("ghost") is None


def test_extract_bearer_token_empty_token():
    with pytest.raises(HTTPException) as exc:
        main._extract_bearer_token("Bearer ")
    assert exc.value.status_code == 401


# ===========================================================================
# init_mongodb
# ===========================================================================
@pytest.fixture(autouse=True)
def _restore_mongo_globals():
    snap = (main.mongo_client, main.db, main.users_collection, main.rate_limiter)
    yield
    (main.mongo_client, main.db, main.users_collection, main.rate_limiter) = snap


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
    assert main.users_collection is not None


def test_init_mongodb_generic_error(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise ValueError("uri mala")

    monkeypatch.setattr(main, "MongoClient", Boom)
    assert main.init_mongodb() is False


def test_get_rate_limiter_reinit_when_none(monkeypatch):
    monkeypatch.setattr(main, "rate_limiter", None)
    monkeypatch.setattr(main, "init_mongodb", lambda: None)
    assert main.get_rate_limiter() is None


# ===========================================================================
# Funciones de acceso a datos — ramas except
# ===========================================================================
def test_get_user_by_username_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.get_user_by_username("x") is None


def test_create_user_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.create_user("x", "p") is False


def test_get_all_users_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.get_all_users() == []


def test_get_all_users_doc_without_id(monkeypatch):
    # Documento sin '_id' ni 'created_at': se cubren las ramas False de ambos if.
    class Coll:
        def find(self, query=None, projection=None):
            return [{"username": "x"}]

    monkeypatch.setattr(main, "users_collection", Coll())
    assert main.get_all_users() == [{"username": "x"}]


def test_update_user_roles_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.update_user_roles("x", True, False) is False


def test_update_user_password_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.update_user_password("x", "p") is False


def test_delete_user_no_db(monkeypatch):
    monkeypatch.setattr(main, "users_collection", None)
    monkeypatch.setattr(main, "init_mongodb", lambda: None)
    assert main.delete_user("x") is False


def test_delete_user_not_found(monkeypatch):
    monkeypatch.setattr(main, "users_collection", FakeUsers())
    assert main.delete_user("ghost") is False


def test_delete_user_exception(monkeypatch):
    monkeypatch.setattr(main, "users_collection", BoomColl())
    assert main.delete_user("x") is False


# ===========================================================================
# get_current_admin_user
# ===========================================================================
def test_get_current_admin_user_no_username():
    import jwt
    tok = jwt.encode({"exp": main.datetime.now(main.timezone.utc) + main.timedelta(hours=1)},
                     main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)
    assert main.get_current_admin_user(tok) is None


def test_get_current_admin_user_invalid_token_reraises():
    with pytest.raises(HTTPException):
        main.get_current_admin_user("token-basura")


def test_get_current_admin_user_generic_error_returns_none(monkeypatch):
    def boom(_token):
        raise RuntimeError("fallo raro")

    monkeypatch.setattr(main, "verify_token", boom)
    assert main.get_current_admin_user("cualquier") is None


# ===========================================================================
# log_admin_action (asíncrono)
# ===========================================================================
def test_log_admin_action_swallows_errors(monkeypatch):
    import asyncio
    monkeypatch.setattr(main.httpx, "AsyncClient", _BoomHTTP)
    asyncio.run(main.log_admin_action("create_user", "actor-1"))


# ===========================================================================
# /auth/login — ramas con limiter None y log-service caído
# ===========================================================================
def test_login_no_limiter_correct_password_and_log_error(monkeypatch):
    users = FakeUsers()
    users.insert_one({"username": "bob", "password": main.hash_password("bob-pass"),
                      "admin": False, "audit": False})
    monkeypatch.setattr(main, "users_collection", users)
    monkeypatch.setattr(main, "rate_limiter", None)
    monkeypatch.setattr(main, "get_rate_limiter", lambda: None)
    monkeypatch.setattr(main.httpx, "AsyncClient", _BoomHTTP)
    resp = client.post("/auth/login", json={"username": "bob", "password": "bob-pass"})
    assert resp.status_code == 200


def test_login_no_limiter_wrong_password_401(monkeypatch):
    users = FakeUsers()
    users.insert_one({"username": "bob", "password": main.hash_password("bob-pass"),
                      "admin": False, "audit": False})
    monkeypatch.setattr(main, "users_collection", users)
    monkeypatch.setattr(main, "rate_limiter", None)
    monkeypatch.setattr(main, "get_rate_limiter", lambda: None)
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 401


# ===========================================================================
# /auth/refresh — token sin username
# ===========================================================================
def test_refresh_token_without_username():
    import jwt
    tok = jwt.encode({"exp": main.datetime.now(main.timezone.utc) + main.timedelta(hours=1)},
                     main.JWT_SECRET, algorithm=main.JWT_ALGORITHM)
    resp = client.post("/auth/refresh", json={"token": tok})
    assert resp.status_code == 401


# ===========================================================================
# Endpoints de admin — ramas defensivas 500 / 503
# ===========================================================================
def test_create_user_fetch_after_create_fails_500(env, monkeypatch):
    # create_user "tiene éxito" pero el usuario no aparece al releerlo -> 500.
    monkeypatch.setattr(main, "create_user", lambda *a, **k: True)
    resp = client.post(
        "/admin/users", json={"username": "fantasma", "password": "secret1"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 500


def test_update_role_not_last_admin_ok(env, monkeypatch):
    # Con dos administradores, quitar el rol admin a uno debe permitirse.
    env.users.insert_one({"username": "admin2", "password": "h", "admin": True, "audit": False})
    resp = client.put(
        "/admin/users/admin2/role", json={"admin": False, "audit": False},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200


def test_update_role_update_fails_500(env, monkeypatch):
    monkeypatch.setattr(main, "update_user_roles", lambda *a, **k: False)
    resp = client.put(
        "/admin/users/bob/role", json={"admin": False, "audit": True},
        headers=_admin_headers(),
    )
    assert resp.status_code == 500


def test_update_role_fetch_updated_fails_500(env, monkeypatch):
    def fake_update(username, admin, audit):
        env.users._docs = [d for d in env.users._docs if d["username"] != username]
        return True

    monkeypatch.setattr(main, "update_user_roles", fake_update)
    resp = client.put(
        "/admin/users/bob/role", json={"admin": False, "audit": True},
        headers=_admin_headers(),
    )
    assert resp.status_code == 500


def test_change_password_update_fails_500(env, monkeypatch):
    monkeypatch.setattr(main, "update_user_password", lambda *a, **k: False)
    resp = client.put(
        "/admin/users/bob/password", json={"new_password": "newsecret"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 500


def test_delete_admin_not_last_ok(env):
    # Hay dos administradores; borrar a uno (admin2) está permitido -> 200.
    env.users.insert_one({"username": "admin2", "password": "h", "admin": True, "audit": False})
    resp = client.delete("/admin/users/admin2", headers=_admin_headers())
    assert resp.status_code == 200


def test_delete_last_admin_blocked_400(env, monkeypatch):
    # El objetivo es admin y, según el recuento, solo queda 1 admin -> 400.
    env.users.insert_one({"username": "admin2", "password": "h", "admin": True, "audit": False})
    monkeypatch.setattr(main, "get_all_users", lambda: [{"username": "admin", "admin": True}])
    resp = client.delete("/admin/users/admin2", headers=_admin_headers())
    assert resp.status_code == 400


def test_delete_user_delete_fails_500(env, monkeypatch):
    monkeypatch.setattr(main, "delete_user", lambda *a, **k: False)
    resp = client.delete("/admin/users/bob", headers=_admin_headers())
    assert resp.status_code == 500


def test_block_info_no_limiter_503(env, monkeypatch):
    monkeypatch.setattr(main, "get_rate_limiter", lambda: None)
    resp = client.get("/admin/users/bob/block-info", headers=_admin_headers())
    assert resp.status_code == 503


def test_unblock_no_limiter_503(env, monkeypatch):
    monkeypatch.setattr(main, "get_rate_limiter", lambda: None)
    resp = client.post("/admin/users/bob/unblock", headers=_admin_headers())
    assert resp.status_code == 503
