"""Tests del pipeline semántico de ``MedicalSearchEngine.search`` y auxiliares.

Se evita el ``__init__`` real (que conecta con servicios externos) creando la
instancia con ``object.__new__`` e inyectando un cliente Qdrant falso. Las
llamadas HTTP a embeddings y reranker se simulan parcheando ``main.requests``.
"""
import main
from main import MedicalSearchEngine, print_traceability


def _engine():
    return object.__new__(MedicalSearchEngine)


class _FakeHit:
    def __init__(self, code, score, search_text="passage: texto tecnico"):
        self.payload = {
            "id": code,
            "title": code,
            "search_text": search_text,
            "metadata": {"hierarchy": []},
        }
        self.score = score


class _FakePoints:
    def __init__(self, hits):
        self.points = hits


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_query = None

    def query_points(self, collection_name=None, query=None, limit=None, **kwargs):
        self.last_query = query
        return _FakePoints(self._hits)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _patch_requests(monkeypatch, vector, rerank_scores):
    def fake_post(url, json=None, timeout=None, **kwargs):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([vector])
        return _FakeResponse(rerank_scores)

    monkeypatch.setattr(main.requests, "post", fake_post)


# ----------------------------------------------------------------------------
# _get_vector_from_docker
# ----------------------------------------------------------------------------
def test_get_vector_from_docker(monkeypatch):
    engine = _engine()
    resp = _FakeResponse([[0.1, 0.2, 0.3]])
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: resp)
    assert engine._get_vector_from_docker("query: x") == [0.1, 0.2, 0.3]


# ----------------------------------------------------------------------------
# search() — ruta semántica
# ----------------------------------------------------------------------------
def test_search_semantic_pipeline(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([_FakeHit("A00.0", 0.8), _FakeHit("B10", 0.6)])
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[3.0, -2.0])

    results = engine.search("dolor de cabeza intenso", top_k=2)
    assert len(results) == 2
    # El primer hit tiene mayor logit -> mayor score híbrido -> va primero.
    assert results[0]["payload"]["id"] == "A00.0"
    assert results[0]["score"] > results[1]["score"]
    assert all(0.0 <= r["score"] <= 1.0 for r in results)


def test_search_uses_enriched_query(monkeypatch):
    engine = _engine()
    client = _FakeClient([_FakeHit("A00.0", 0.8)])
    engine.client = client
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[1.0])

    engine.search("tos", top_k=1, enriched_query="infeccion respiratoria aguda")
    # El texto enriquecido se prefija con 'query: ' al pedir el embedding, pero
    # el vector es el mismo; comprobamos que la búsqueda se ejecutó.
    assert client.last_query == [0.1, 0.2]


def test_search_reranker_failure_falls_back_to_vector(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([_FakeHit("A00.0", 0.7)])

    def fake_post(url, json=None, timeout=None, **kwargs):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([[0.1, 0.2]])
        raise RuntimeError("reranker caido")

    monkeypatch.setattr(main.requests, "post", fake_post)
    results = engine.search("dolor", top_k=1)
    # Con el reranker caído, el score es el del vector (fallback).
    assert results[0]["score"] == 0.7


def test_search_no_hits_returns_empty(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([])
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[])
    assert engine.search("algo raro", top_k=3) == []


def test_search_code_shortcut(monkeypatch):
    engine = _engine()

    captured = {}

    def fake_exact(code, top_k=5):
        captured["code"] = code
        return [{"score": 1.0, "payload": {"id": code}}]

    engine.search_by_code_exact = fake_exact
    results = engine.search("A00.0", top_k=5)
    assert results[0]["payload"]["id"] == "A00.0"
    assert captured["code"] == "A00.0"


# ----------------------------------------------------------------------------
# print_traceability (no debe lanzar)
# ----------------------------------------------------------------------------
def test_print_traceability_empty(capsys):
    print_traceability([])
    assert "No se encontraron" in capsys.readouterr().out


def test_print_traceability_with_results(capsys):
    results = [
        {
            "score": 0.9,
            "payload": {
                "id": "A00.0",
                "title": "Colera",
                "metadata": {"hierarchy": [{"code": "A00-A09", "title": "Infecciosas"}]},
            },
        }
    ]
    print_traceability(results)
    out = capsys.readouterr().out
    assert "A00.0" in out
    assert "Colera" in out
