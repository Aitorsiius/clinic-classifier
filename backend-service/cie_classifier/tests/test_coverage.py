"""Tests de cobertura para ``main.py`` y ``api.py`` del backend.

Cubren las ramas que el resto de la suite no toca:

- ``main.py``: guardas de texto vacío, ramas sin candidatos del desempate
  conservador, ``_wait_for_service`` (probe listo / nunca listo), ``__init__``
  del motor con dependencias simuladas (embeddings/reranker/Qdrant), errores de
  ``_get_vector_from_docker`` y ``search_by_code_exact``, y los caminos
  alternativos de ``search`` (API antigua de Qdrant, reranker no-lista, atajo por
  código sin coincidencia exacta).
- ``api.py``: enriquecimiento por IA (sin datos / consulta no médica), logging
  seguro (camino feliz y absorción de errores), formateo desde objetos, y las
  ramas de error de los endpoints ``/search`` y ``/export-csv``, además del
  arranque con el motor listo.
"""
import asyncio
import importlib.util

import pytest
from fastapi.testclient import TestClient

import api
import main


# ===========================================================================
# main.py — guardas de texto vacío
# ===========================================================================
def test_detect_laterality_empty():
    assert main.detect_laterality("") == set()


def test_detect_anatomical_sites_empty():
    assert main.detect_anatomical_sites("") == set()


def test_content_tokens_empty():
    assert main._content_tokens("") == set()


def test_lexical_overlap_empty_query_returns_zero():
    # La consulta solo tiene stopwords -> sin tokens de contenido -> 0.0.
    assert main.lexical_overlap("de la el", "anemia ferropenica") == 0.0


def test_complication_status_only_stopwords():
    # Tras "con" solo hay un token demasiado corto/stopword -> sin complicación (0).
    assert main.complication_status("Cistitis con la", "cistitis aguda") == 0


def test_is_unspecified_variant_non_dict():
    assert main.is_unspecified_variant("no-dict") is False


def test_is_primary_default_variant_non_dict():
    assert main.is_primary_default_variant(None) is False


def test_promote_no_conservative_candidate_returns_unchanged():
    # Empate técnico pero ninguna variante es "no especificada" ni "primaria".
    results = [
        {"score": 0.88, "payload": {"id": "M05.1", "title": "Artritis de mano izquierda"}},
        {"score": 0.87, "payload": {"id": "M05.2", "title": "Artritis de mano derecha"}},
    ]
    out = main.promote_conservative_default(results, "artritis")
    assert out[0]["payload"]["id"] == "M05.1"


# ===========================================================================
# main.py — _wait_for_service
# ===========================================================================
def test_wait_for_service_probe_ready(capsys):
    main.MedicalSearchEngine._wait_for_service(
        "x", "url", lambda: True, max_retries=1, retry_delay=0
    )
    assert "establecida" in capsys.readouterr().out


def test_wait_for_service_probe_never_ready():
    # probe siempre False: agota reintentos y sale sin lanzar excepción.
    result = main.MedicalSearchEngine._wait_for_service(
        "x", "url", lambda: False, max_retries=2, retry_delay=0
    )
    assert result is None


# ===========================================================================
# main.py — MedicalSearchEngine.__init__
# ===========================================================================
class _Resp200:
    status_code = 200


class _Resp503:
    status_code = 503


def _patch_healthy_deps(monkeypatch, get_resp=_Resp200):
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: _Resp200())
    monkeypatch.setattr(main.requests, "get", lambda *a, **k: get_resp())


def test_engine_init_success(monkeypatch):
    _patch_healthy_deps(monkeypatch)

    class FakeQdrant:
        def __init__(self, path=None):
            pass

        def get_collection(self, name):
            return object()

    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    engine = main.MedicalSearchEngine()
    assert engine.client is not None


def test_engine_init_reranker_not_ready_then_continues(monkeypatch):
    # Embeddings OK; reranker responde !=200 (probe False): agota reintentos y sigue.
    _patch_healthy_deps(monkeypatch, get_resp=_Resp503)

    class FakeQdrant:
        def __init__(self, path=None):
            pass

        def get_collection(self, name):
            return object()

    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    engine = main.MedicalSearchEngine()
    assert engine.client is not None


def test_engine_init_qdrant_missing_collection(monkeypatch):
    _patch_healthy_deps(monkeypatch)

    class FakeQdrant:
        def __init__(self, path=None):
            pass

        def get_collection(self, name):
            raise RuntimeError("colección inexistente")

    monkeypatch.setattr(main, "QdrantClient", FakeQdrant)
    with pytest.raises(ValueError):
        main.MedicalSearchEngine()


# ===========================================================================
# main.py — _get_vector_from_docker / search_by_code_exact
# ===========================================================================
def test_get_vector_from_docker_http_error(monkeypatch):
    class Resp:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(main.requests, "post", lambda *a, **k: Resp())
    engine = object.__new__(main.MedicalSearchEngine)
    with pytest.raises(main.requests.exceptions.HTTPError):
        engine._get_vector_from_docker("query: x")


def test_search_by_code_exact_handles_exception():
    class BoomClient:
        def scroll(self, **k):
            raise RuntimeError("scroll caído")

    engine = object.__new__(main.MedicalSearchEngine)
    engine.client = BoomClient()
    assert engine.search_by_code_exact("A00.0", top_k=5) == []


# ===========================================================================
# main.py — search() (rutas alternativas)
# ===========================================================================
class _FakeHit:
    def __init__(self, code, score, search_text="passage: texto", title=None):
        self.payload = {
            "id": code,
            "title": title or code,
            "search_text": search_text,
            "metadata": {"hierarchy": []},
        }
        self.score = score


class _FakePoints:
    def __init__(self, hits):
        self.points = hits


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_search_falls_back_to_old_qdrant_api(monkeypatch):
    # query_points lanza AttributeError -> se usa el API antiguo self.client.search().
    class OldClient:
        def __init__(self, hits):
            self._hits = hits

        def query_points(self, **k):
            raise AttributeError("sin query_points")

        def search(self, collection_name=None, query_vector=None, limit=None):
            return self._hits

    engine = object.__new__(main.MedicalSearchEngine)
    engine.client = OldClient([_FakeHit("A00.0", 0.8)])

    def fake_post(url, json=None, timeout=None, **k):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([[0.1, 0.2]])
        return _FakeResponse([1.0])

    monkeypatch.setattr(main.requests, "post", fake_post)
    results = engine.search("dolor de cabeza", top_k=1)
    assert results[0]["payload"]["id"] == "A00.0"


def test_search_reranker_non_list_scores(monkeypatch):
    class Client:
        def query_points(self, **k):
            return _FakePoints([_FakeHit("A00.0", 0.7)])

    engine = object.__new__(main.MedicalSearchEngine)
    engine.client = Client()

    def fake_post(url, json=None, timeout=None, **k):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([[0.1, 0.2]])
        return _FakeResponse({"no": "es una lista"})  # rerank devuelve no-lista

    monkeypatch.setattr(main.requests, "post", fake_post)
    results = engine.search("dolor", top_k=1)
    # raw_scores no es lista -> [] -> fallback al score del vector.
    assert results[0]["score"] == 0.7


def test_search_code_looks_like_but_no_exact_match(monkeypatch):
    class Client:
        def query_points(self, **k):
            return _FakePoints([_FakeHit("A00.0", 0.8)])

    engine = object.__new__(main.MedicalSearchEngine)
    engine.client = Client()
    # Parece código, pero la búsqueda exacta no devuelve nada -> cae al pipeline semántico.
    engine.search_by_code_exact = lambda code, top_k=5: []

    def fake_post(url, json=None, timeout=None, **k):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([[0.1, 0.2]])
        return _FakeResponse([1.0])

    monkeypatch.setattr(main.requests, "post", fake_post)
    results = engine.search("A00.0", top_k=1)
    assert results[0]["payload"]["id"] == "A00.0"


# ===========================================================================
# api.py — _handle_ai_enrichment
# ===========================================================================
def test_handle_ai_enrichment_enrich_returns_none(monkeypatch):
    async def fake_enrich(query):
        return None

    monkeypatch.setattr(api, "enrich_query_with_ai", fake_enrich)
    request = api.SearchRequest(query="q", use_ai=True)
    result = asyncio.run(api._handle_ai_enrichment(request))
    assert result["enriched_query"] is None
    assert result["assistant_block"] is None


def test_handle_ai_enrichment_invalid_medical_query(monkeypatch):
    async def fake_enrich(query):
        return {
            "enriched_query": "algo",
            "is_valid_medical_query": False,
            "diagnosis": "d",
            "improvement_tips": [],
        }

    monkeypatch.setattr(api, "enrich_query_with_ai", fake_enrich)
    request = api.SearchRequest(query="q", use_ai=True)
    result = asyncio.run(api._handle_ai_enrichment(request))
    # is_valid_medical_query False -> no se adopta el enriched_query...
    assert result["enriched_query"] is None
    # ...pero el bloque del asistente sí se construye.
    assert result["assistant_block"]["diagnosis"] == "d"
    assert result["effective_used_ai"] is True


# ===========================================================================
# api.py — _safe_async_log
# ===========================================================================
class _FakeReqClient:
    host = "1.2.3.4"


class _FakeReq:
    client = _FakeReqClient()


def _formatted():
    return api.format_search_results(
        [{"score": 0.5, "payload": {"id": "B10", "title": "x", "metadata": {"hierarchy": []}}}]
    )


def test_safe_async_log_happy_path(monkeypatch):
    recorded = {}

    async def fake_register(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(api, "register_search_log", fake_register)
    request = api.SearchRequest(query="q", top_k=5)
    asyncio.run(api._safe_async_log(
        "s", "u", request, _FakeReq(), 5, _formatted(), "success",
        10.0, True, {"diagnosis": "x"},
    ))
    assert recorded["session_id"] == "s"
    assert recorded["results_count"] == 1


def test_safe_async_log_no_ids_returns_early(monkeypatch):
    async def boom(**kwargs):
        raise AssertionError("no debería llamarse sin ids")

    monkeypatch.setattr(api, "register_search_log", boom)
    request = api.SearchRequest(query="q")
    asyncio.run(api._safe_async_log(None, None, request, _FakeReq(), 5, [], "success"))


def test_safe_async_log_swallows_errors(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("log-service caído")

    monkeypatch.setattr(api, "register_search_log", boom)
    request = api.SearchRequest(query="q")
    # No debe propagar aunque el registro falle.
    asyncio.run(api._safe_async_log(
        "s", "u", request, _FakeReq(), 5, _formatted(), "error", 0.0, False, None, "err",
    ))


# ===========================================================================
# api.py — formateo desde objetos (no-dict)
# ===========================================================================
class _HierObj:
    def __init__(self, id, title):
        self.id = id
        self.title = title


def test_build_hierarchy_items_from_object():
    payload = {"metadata": {"hierarchy": [_HierObj("A00", "Cap")]}}
    items = api._build_hierarchy_items(payload)
    assert items[0].code == "A00"
    assert items[0].title == "Cap"


class _ResultObj:
    def __init__(self):
        self.score = 0.7
        self.payload = {"id": "X1", "title": "t", "metadata": {"hierarchy": []}}


def test_to_search_result_from_object():
    r = api._to_search_result(_ResultObj())
    assert r.score == 0.7
    assert r.payload.id == "X1"


# ===========================================================================
# api.py — ramas de error de endpoints
# ===========================================================================
def test_search_engine_error_returns_500(monkeypatch):
    class BoomEngine:
        def search(self, *a, **k):
            raise RuntimeError("motor roto")

    monkeypatch.setattr(api, "search_engine", BoomEngine())
    resp = TestClient(api.app).post("/search", json={"query": "x"})
    assert resp.status_code == 500


def test_export_csv_error_returns_500():
    # El segundo registro tiene una clave que no está en los fieldnames del primero
    # -> csv.DictWriter lanza -> 500.
    resp = TestClient(api.app).post("/export-csv", json=[{"a": 1}, {"b": 2}])
    assert resp.status_code == 500


# ===========================================================================
# api.py — arranque con el motor listo
# ===========================================================================
def test_api_import_with_engine_ready(monkeypatch):
    class OkEngine:
        def __init__(self):
            pass

    monkeypatch.setattr(main, "MedicalSearchEngine", OkEngine)
    spec = importlib.util.spec_from_file_location("api_fresh_cov", api.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.search_engine is not None
