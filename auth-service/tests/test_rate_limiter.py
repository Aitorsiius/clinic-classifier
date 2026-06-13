"""Tests unitarios del rate limiter (``rate_limiter.py``).

Se usa una implementación en memoria de las colecciones de MongoDB para no
depender de una base de datos real. Cubren el registro de intentos fallidos, el
bloqueo por umbral, el desbloqueo, la información forense y la limpieza.
"""
import copy
from datetime import datetime, timezone

import rate_limiter as rl
from rate_limiter import LoginRateLimiter, _to_iso


# ----------------------------------------------------------------------------
# Doble de MongoDB en memoria
# ----------------------------------------------------------------------------
class _Result:
    def __init__(self, inserted_id=None, modified_count=0, deleted_count=0):
        self.inserted_id = inserted_id
        self.modified_count = modified_count
        self.deleted_count = deleted_count


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=-1):
        self._docs.sort(
            key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=direction < 0,
        )
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


def _match(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
        elif isinstance(cond, dict) and "$gte" in cond:
            value = doc.get(key)
            if value is None or value < cond["$gte"]:
                return False
        else:
            if doc.get(key) != cond:
                return False
    return True


class FakeCollection:
    def __init__(self):
        self._docs = []
        self._counter = 0

    def create_index(self, *args, **kwargs):
        return None

    def insert_one(self, doc):
        self._counter += 1
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", self._counter)
        self._docs.append(stored)
        return _Result(inserted_id=stored["_id"])

    def find_one(self, query):
        for doc in self._docs:
            if _match(doc, query):
                return copy.deepcopy(doc)
        return None

    def find(self, query, projection=None):
        return _Cursor([copy.deepcopy(d) for d in self._docs if _match(d, query)])

    def count_documents(self, query):
        return sum(1 for d in self._docs if _match(d, query))

    def update_many(self, query, update):
        modified = 0
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                modified += 1
        return _Result(modified_count=modified)

    def delete_many(self, query):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not _match(d, query)]
        return _Result(deleted_count=before - len(self._docs))


class FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, FakeCollection())


def _make_limiter():
    return LoginRateLimiter(FakeDB())


# ----------------------------------------------------------------------------
# _to_iso
# ----------------------------------------------------------------------------
def test_to_iso_none():
    assert _to_iso(None) is None


def test_to_iso_naive_is_marked_utc():
    naive = datetime(2025, 1, 1, 12, 0, 0)
    assert _to_iso(naive).endswith("+00:00")


def test_to_iso_aware():
    aware = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _to_iso(aware).startswith("2025-01-01T12:00:00")


# ----------------------------------------------------------------------------
# LoginRateLimiter
# ----------------------------------------------------------------------------
def test_record_failed_attempt_decrements_remaining():
    limiter = _make_limiter()
    result = limiter.record_failed_attempt("u1", "1.2.3.4")
    assert result["blocked"] is False
    assert result["remaining"] == rl.MAX_FAILED_ATTEMPTS - 1


def test_blocks_after_threshold():
    limiter = _make_limiter()
    result = None
    for _ in range(rl.MAX_FAILED_ATTEMPTS):
        result = limiter.record_failed_attempt("u1", "1.2.3.4")
    assert result["blocked"] is True
    assert limiter.is_blocked(user_id="u1") is True
    assert "u1" in limiter.get_blocked_user_ids()


def test_already_blocked_returns_existing_block():
    limiter = _make_limiter()
    for _ in range(rl.MAX_FAILED_ATTEMPTS):
        limiter.record_failed_attempt("u1", "1.2.3.4")
    again = limiter.record_failed_attempt("u1", "1.2.3.4")
    assert again["blocked"] is True
    assert again["remaining"] == 0


def test_unblock_clears_block_and_attempts():
    limiter = _make_limiter()
    for _ in range(rl.MAX_FAILED_ATTEMPTS):
        limiter.record_failed_attempt("u1", "1.2.3.4")
    assert limiter.is_blocked(user_id="u1")
    assert limiter.unblock("u1", admin_user_id="admin") is True
    assert limiter.is_blocked(user_id="u1") is False
    # Un segundo desbloqueo no encuentra bloqueos activos.
    assert limiter.unblock("u1") is False


def test_reset_on_success_clears_attempts():
    limiter = _make_limiter()
    limiter.record_failed_attempt("u1", "1.2.3.4")
    limiter.reset_on_success("u1")
    result = limiter.record_failed_attempt("u1", "1.2.3.4")
    assert result["remaining"] == rl.MAX_FAILED_ATTEMPTS - 1


def test_get_block_info():
    limiter = _make_limiter()
    for _ in range(rl.MAX_FAILED_ATTEMPTS):
        limiter.record_failed_attempt("u1", "9.9.9.9")
    info = limiter.get_block_info("u1")
    assert info["blocked"] is True
    assert info["block_count"] >= 1
    assert len(info["failed_attempts"]) >= 1
    assert info["current_block"]["ip_address"] == "9.9.9.9"


def test_get_block_info_unknown_user_is_empty():
    limiter = _make_limiter()
    info = limiter.get_block_info("does-not-exist")
    assert info["blocked"] is False
    assert info["block_count"] == 0
    assert info["failed_attempts"] == []
    assert info["current_block"] is None


def test_delete_user_records():
    limiter = _make_limiter()
    limiter.record_failed_attempt("u1", "1.2.3.4")
    assert limiter.delete_user_records("u1") is True
    assert limiter.delete_user_records("u1") is False
