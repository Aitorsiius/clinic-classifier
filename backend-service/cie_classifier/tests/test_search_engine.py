"""Tests unitarios del motor de búsqueda (``main.MedicalSearchEngine``).

Se prueban las funciones que NO requieren conexión a embeddings/reranker/Qdrant:
- ``_looks_like_code``: detección de códigos CIE-10 mediante expresión regular.
- ``search_by_code_exact``: búsqueda exacta/parcial sobre un cliente Qdrant
  simulado.

Para evitar el ``__init__`` (que conecta con servicios externos) se crea la
instancia con ``object.__new__`` y se inyecta un cliente falso.
"""
from main import MedicalSearchEngine


def _engine_without_init():
    return object.__new__(MedicalSearchEngine)


# ----------------------------------------------------------------------------
# _looks_like_code
# ----------------------------------------------------------------------------
def test_looks_like_code_true():
    engine = _engine_without_init()
    assert engine._looks_like_code("A00.0") is True
    assert engine._looks_like_code("I10") is True
    assert engine._looks_like_code("i40.1") is True  # se normaliza a mayúsculas


def test_looks_like_code_false():
    engine = _engine_without_init()
    assert engine._looks_like_code("dolor de cabeza") is False
    assert engine._looks_like_code("") is False
    assert engine._looks_like_code("12345") is False


# ----------------------------------------------------------------------------
# search_by_code_exact
# ----------------------------------------------------------------------------
class _FakePoint:
    def __init__(self, payload):
        self.payload = payload


class _FakeClient:
    def __init__(self, points):
        self._points = points

    def scroll(self, collection_name=None, limit=None):
        return self._points, None


def test_search_by_code_exact_returns_exact_first():
    engine = _engine_without_init()
    engine.client = _FakeClient(
        [
            _FakePoint({"id": "A00.0", "title": "Colera"}),
            _FakePoint({"id": "B99", "title": "Otro"}),
        ]
    )
    results = engine.search_by_code_exact("A00.0", top_k=5)
    assert results[0]["score"] == 1.0
    assert results[0]["payload"]["id"] == "A00.0"


def test_search_by_code_exact_includes_partial_matches():
    engine = _engine_without_init()
    engine.client = _FakeClient(
        [
            _FakePoint({"id": "A00", "title": "categoria"}),
            _FakePoint({"id": "A00.0", "title": "sub"}),
            _FakePoint({"id": "A00.1", "title": "sub2"}),
        ]
    )
    results = engine.search_by_code_exact("A00", top_k=5)
    codes = [r["payload"]["id"] for r in results]
    assert codes[0] == "A00"
    assert results[0]["score"] == 1.0
    assert "A00.0" in codes and "A00.1" in codes
    assert all(r["score"] in (1.0, 0.99) for r in results)


def test_search_by_code_exact_no_match_returns_empty():
    engine = _engine_without_init()
    engine.client = _FakeClient([_FakePoint({"id": "Z99", "title": "x"})])
    assert engine.search_by_code_exact("A00.0", top_k=5) == []
