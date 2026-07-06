"""Tests de cobertura de las ramas de error de ``rate_limiter.py``.

Inyecta colecciones cuyas operaciones lanzan para ejercitar todos los bloques
``except`` (índices, consultas, registro de intentos, bloqueo, desbloqueo,
información forense y borrado), además de las ramas de parámetros de
``get_active_block``.
"""
import rate_limiter as rl
from rate_limiter import LoginRateLimiter


class _Result:
    def __init__(self, inserted_id=None, modified_count=0, deleted_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def __iter__(self):
        return iter(self._docs)


class ConfigColl:
    """Colección configurable: cada método lanza si está en ``raise_on``."""

    def __init__(self, raise_on=(), count_value=0):
        self.raise_on = set(raise_on)
        self.count_value = count_value

    def _maybe(self, name):
        if name in self.raise_on:
            raise RuntimeError(f"{name} boom")

    def create_index(self, *a, **k):
        self._maybe("create_index")

    def insert_one(self, doc):
        self._maybe("insert_one")
        return _Result(inserted_id="id1")

    def find_one(self, query):
        self._maybe("find_one")
        return None

    def find(self, query, projection=None):
        self._maybe("find")
        return _Cursor([])

    def count_documents(self, query):
        self._maybe("count_documents")
        return self.count_value

    def update_many(self, query, update):
        self._maybe("update_many")
        return _Result(modified_count=0)

    def delete_many(self, query):
        self._maybe("delete_many")
        return _Result(deleted_count=0)


class ConfigDB:
    def __init__(self, attempts, blocks):
        self._cols = {"login_attempts": attempts, "login_blocks": blocks}

    def __getitem__(self, name):
        return self._cols[name]


def _limiter(attempts=None, blocks=None):
    return LoginRateLimiter(ConfigDB(attempts or ConfigColl(), blocks or ConfigColl()))


def test_ensure_indexes_swallows_errors():
    lim = _limiter(ConfigColl(raise_on={"create_index"}), ConfigColl(raise_on={"create_index"}))
    assert lim is not None


def test_get_active_block_ip_only_and_none():
    lim = _limiter()
    assert lim.get_active_block() is None  # sin condiciones -> None
    assert lim.get_active_block(ip_address="1.2.3.4") is None  # solo IP


def test_get_active_block_find_error_returns_none():
    lim = _limiter(blocks=ConfigColl(raise_on={"find_one"}))
    assert lim.get_active_block(user_id="u1") is None


def test_get_blocked_user_ids_error_returns_empty():
    lim = _limiter(blocks=ConfigColl(raise_on={"find"}))
    assert lim.get_blocked_user_ids() == set()


def test_record_failed_attempt_insert_error_swallowed():
    lim = _limiter(attempts=ConfigColl(raise_on={"insert_one"}))
    assert lim.record_failed_attempt("u1", "1.2.3.4")["blocked"] is False


def test_record_failed_attempt_count_error_defaults_zero():
    lim = _limiter(attempts=ConfigColl(raise_on={"count_documents"}))
    assert lim.record_failed_attempt("u1", "1.2.3.4")["blocked"] is False


def test_create_block_insert_error_swallowed():
    attempts = ConfigColl(count_value=rl.MAX_FAILED_ATTEMPTS)
    blocks = ConfigColl(raise_on={"insert_one"})
    out = _limiter(attempts=attempts, blocks=blocks).record_failed_attempt("u1", "1.2.3.4")
    assert out["blocked"] is True
    assert out["block"]["user_id"] == "u1"


def test_clear_attempts_error_swallowed():
    # reset_on_success -> _clear_attempts -> delete_many lanza; no debe propagar.
    _limiter(attempts=ConfigColl(raise_on={"delete_many"})).reset_on_success("u1")


def test_unblock_update_error_returns_false():
    assert _limiter(blocks=ConfigColl(raise_on={"update_many"})).unblock("u1") is False


def test_get_block_info_attempts_find_error():
    info = _limiter(attempts=ConfigColl(raise_on={"find"})).get_block_info("u1")
    assert info["failed_attempts"] == []


def test_get_block_info_count_error_defaults_zero():
    info = _limiter(blocks=ConfigColl(raise_on={"count_documents"})).get_block_info("u1")
    assert info["block_count"] == 0


def test_delete_user_records_error_returns_false():
    assert _limiter(attempts=ConfigColl(raise_on={"delete_many"})).delete_user_records("u1") is False
