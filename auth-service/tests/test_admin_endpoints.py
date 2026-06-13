"""Tests de los endpoints del ``auth-service`` con MongoDB y rate-limiter
simulados en memoria.

Cubren login (incluida la política anti fuerza bruta), verificación/refresco de
token, registro y todos los endpoints de administración (listar, crear, cambiar
rol, cambiar contraseña, eliminar, info de bloqueo y desbloqueo).
"""
import pytest
from fastapi.testclient import TestClient

import main


# ---------------------------------------------------------------------------
# Dobles de prueba (MongoDB + rate limiter + httpx)
# ---------------------------------------------------------------------------
class FakeResult:
    def __init__(self, inserted_id=None, modified_count=0, matched_count=0, deleted_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.matched_count = matched_count
        self.deleted_count = deleted_count


class FakeUsers:
    """Colección de usuarios en memoria con la API mínima de pymongo usada."""

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


class FakeLimiter:
    def __init__(self):
        self.blocked_ids = set()
        self.block_on_attempt = False
        self.unblock_result = True

    def is_blocked(self, user_id=None):
        return user_id in self.blocked_ids

    def record_failed_attempt(self, user_id, ip, ua):
        return {"blocked": self.block_on_attempt}

    def reset_on_success(self, user_id):
        pass

    def get_blocked_user_ids(self):
        return set(self.blocked_ids)

    def delete_user_records(self, user_id):
        pass

    def get_block_info(self, user_id):
        return {"failed_attempts": [], "block_count": 0, "current_block": None}

    def unblock(self, user_id, admin_user_id):
        return self.unblock_result


class _FakeHTTPResp:
    status_code = 200

    def json(self):
        return {}


class _FakeHTTPClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def post(self, *a, **k):
        return _FakeHTTPResp()


@pytest.fixture
def env(monkeypatch):
    """Inyecta colección y rate-limiter falsos, con un admin y un usuario."""
    users = FakeUsers()
    users.insert_one({
        "username": "admin", "password": main.hash_password("admin-pass"),
        "admin": True, "audit": False,
    })
    users.insert_one({
        "username": "bob", "password": main.hash_password("bob-pass"),
        "admin": False, "audit": False,
    })
    limiter = FakeLimiter()
    monkeypatch.setattr(main, "users_collection", users)
    monkeypatch.setattr(main, "rate_limiter", limiter)
    monkeypatch.setattr(main.httpx, "AsyncClient", _FakeHTTPClient)
    return type("Env", (), {"users": users, "limiter": limiter})


@pytest.fixture
def client():
    return TestClient(main.app)


def _admin_headers():
    token, _ = main.create_token("admin")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["service"] == "auth-service"


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------
def test_login_success(env, client):
    resp = client.post("/auth/login", json={"username": "bob", "password": "bob-pass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user_data"]["username"] == "bob"


def test_login_unknown_user_401(env, client):
    resp = client.post("/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


def test_login_wrong_password_401(env, client):
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 401


def test_login_wrong_password_triggers_block_403(env, client):
    env.limiter.block_on_attempt = True
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 403


def test_login_already_blocked_403(env, client):
    user = env.users.find_one({"username": "bob"})
    env.limiter.blocked_ids.add(str(user["_id"]))
    resp = client.post("/auth/login", json={"username": "bob", "password": "bob-pass"})
    assert resp.status_code == 403


def test_login_db_unavailable_503(monkeypatch, client):
    monkeypatch.setattr(main, "users_collection", None)
    monkeypatch.setattr(main, "init_mongodb", lambda: False)
    resp = client.post("/auth/login", json={"username": "bob", "password": "x"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /auth/verify, /auth/refresh, /auth/validate-token
# ---------------------------------------------------------------------------
def test_verify_valid_token(client):
    token, _ = main.create_token("alice")
    body = client.post("/auth/verify", json={"token": token}).json()
    assert body["valid"] is True
    assert body["username"] == "alice"


def test_verify_invalid_token(client):
    body = client.post("/auth/verify", json={"token": "garbage"}).json()
    assert body["valid"] is False


def test_refresh_valid(client):
    token, _ = main.create_token("alice")
    resp = client.post("/auth/refresh", json={"token": token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_refresh_invalid_token_401(client):
    resp = client.post("/auth/refresh", json={"token": "garbage"})
    assert resp.status_code == 401


def test_validate_token_valid(client):
    token, _ = main.create_token("alice")
    resp = client.get("/auth/validate-token", params={"token": token})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_validate_token_invalid_401(client):
    resp = client.get("/auth/validate-token", params={"token": "garbage"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/register
# ---------------------------------------------------------------------------
def test_register_success(env, client):
    resp = client.post("/auth/register", json={"username": "carol", "password": "secret1"})
    assert resp.status_code == 200
    assert env.users.find_one({"username": "carol"}) is not None


def test_register_duplicate_400(env, client):
    resp = client.post("/auth/register", json={"username": "bob", "password": "secret1"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /admin/users (listar)
# ---------------------------------------------------------------------------
def test_list_users_success(env, client):
    resp = client.get("/admin/users", headers=_admin_headers())
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert {"admin", "bob"} <= usernames


def test_list_users_missing_auth_401(env, client):
    assert client.get("/admin/users").status_code == 401


def test_list_users_non_admin_403(env, client):
    token, _ = main.create_token("bob")
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /admin/users (crear)
# ---------------------------------------------------------------------------
def test_create_user_success(env, client):
    resp = client.post(
        "/admin/users",
        json={"username": "dave", "password": "secret1", "admin": False, "audit": True},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "dave"


def test_create_user_short_username_400(env, client):
    resp = client.post(
        "/admin/users", json={"username": "ab", "password": "secret1"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_create_user_short_password_400(env, client):
    resp = client.post(
        "/admin/users", json={"username": "dave", "password": "123"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_create_user_duplicate_400(env, client):
    resp = client.post(
        "/admin/users", json={"username": "bob", "password": "secret1"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /admin/users/{username}/role
# ---------------------------------------------------------------------------
def test_update_role_success(env, client):
    resp = client.put(
        "/admin/users/bob/role", json={"admin": False, "audit": True},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["audit"] is True


def test_update_role_user_not_found_404(env, client):
    resp = client.put(
        "/admin/users/ghost/role", json={"admin": False, "audit": True},
        headers=_admin_headers(),
    )
    assert resp.status_code == 404


def test_update_role_last_admin_400(env, client):
    resp = client.put(
        "/admin/users/admin/role", json={"admin": False, "audit": False},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /admin/users/{username}/password
# ---------------------------------------------------------------------------
def test_change_password_success(env, client):
    resp = client.put(
        "/admin/users/bob/password", json={"new_password": "newsecret"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200


def test_change_password_user_not_found_404(env, client):
    resp = client.put(
        "/admin/users/ghost/password", json={"new_password": "newsecret"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 404


def test_change_password_too_short_400(env, client):
    resp = client.put(
        "/admin/users/bob/password", json={"new_password": "123"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /admin/users/{username} (eliminar)
# ---------------------------------------------------------------------------
def test_delete_user_success(env, client):
    resp = client.delete("/admin/users/bob", headers=_admin_headers())
    assert resp.status_code == 200
    assert env.users.find_one({"username": "bob"}) is None


def test_delete_self_400(env, client):
    resp = client.delete("/admin/users/admin", headers=_admin_headers())
    assert resp.status_code == 400


def test_delete_user_not_found_404(env, client):
    resp = client.delete("/admin/users/ghost", headers=_admin_headers())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /admin/users/{username}/block-info y /unblock
# ---------------------------------------------------------------------------
def test_block_info_success(env, client):
    resp = client.get("/admin/users/bob/block-info", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["username"] == "bob"


def test_block_info_user_not_found_404(env, client):
    resp = client.get("/admin/users/ghost/block-info", headers=_admin_headers())
    assert resp.status_code == 404


def test_unblock_success(env, client):
    resp = client.post("/admin/users/bob/unblock", headers=_admin_headers())
    assert resp.status_code == 200


def test_unblock_not_blocked_400(env, client):
    env.limiter.unblock_result = False
    resp = client.post("/admin/users/bob/unblock", headers=_admin_headers())
    assert resp.status_code == 400


def test_unblock_user_not_found_404(env, client):
    resp = client.post("/admin/users/ghost/unblock", headers=_admin_headers())
    assert resp.status_code == 404
