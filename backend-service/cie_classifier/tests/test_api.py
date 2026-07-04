"""Tests de la capa API del backend (``api.py``) con ``TestClient``.

Cubren las funciones de formateo de resultados, el enriquecimiento por IA y los
endpoints (``/``, ``/health``, ``/search``, ``/export-csv``) inyectando un motor
de búsqueda falso y simulando httpx donde hace falta. No requieren red.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import api


# ----------------------------------------------------------------------------
# Motor de búsqueda falso
# ----------------------------------------------------------------------------
class FakeEngine:
    def __init__(self, results=None):
        self._results = results if results is not None else [
            {
                "score": 0.91,
                "payload": {
                    "id": "A00.0",
                    "title": "Colera",
                    "search_text": "colera vibrio",
                    "metadata": {"hierarchy": [{"id": "A00-A09", "title": "Infecciosas"}]},
                },
            }
        ]
        self.calls = []

    def search(self, user_query, top_k=5, enriched_query=None):
        self.calls.append((user_query, top_k, enriched_query))
        return self._results


@pytest.fixture
def client_with_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(api, "search_engine", engine)
    return TestClient(api.app), engine


# ----------------------------------------------------------------------------
# Funciones de formateo
# ----------------------------------------------------------------------------
def test_build_hierarchy_items_from_dict():
    payload = {"metadata": {"hierarchy": [{"id": "A00", "title": "Cap"}]}}
    items = api._build_hierarchy_items(payload)
    assert items[0].code == "A00"
    assert items[0].title == "Cap"


def test_build_hierarchy_items_invalid_payload():
    assert api._build_hierarchy_items("no-dict") == []


def test_to_search_result_from_dict():
    result = api._to_search_result(
        {"score": 0.5, "payload": {"id": "B10", "title": "x", "metadata": {"hierarchy": []}}}
    )
    assert result.score == 0.5
    assert result.original_score == 0.5
    assert result.payload.id == "B10"


def test_format_search_results():
    results = api.format_search_results(
        [{"score": 0.5, "payload": {"id": "B10", "title": "x", "metadata": {"hierarchy": []}}}]
    )
    assert len(results) == 1
    assert results[0].payload.id == "B10"


# ----------------------------------------------------------------------------
# Endpoints simples
# ----------------------------------------------------------------------------
def test_root_endpoint(client_with_engine):
    client, _ = client_with_engine
    data = client.get("/").json()
    assert data["service"] == "CIE-10 Classifier Backend"
    assert data["search_engine"] == "ready"


def test_health_endpoint(client_with_engine):
    client, _ = client_with_engine
    data = client.get("/health").json()
    assert data["status"] == "healthy"
    assert data["search_engine"] == "ready"


def test_health_endpoint_engine_not_ready(monkeypatch):
    monkeypatch.setattr(api, "search_engine", None)
    data = TestClient(api.app).get("/health").json()
    assert data["search_engine"] == "not_ready"


# ----------------------------------------------------------------------------
# /search
# ----------------------------------------------------------------------------
def test_search_basic(client_with_engine):
    client, engine = client_with_engine
    resp = client.post("/search", json={"query": "colera", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["used_ai"] is False
    assert body["results"][0]["payload"]["id"] == "A00.0"
    assert engine.calls[0][1] == 3  # top_k propagado


def test_search_caps_top_k_at_20(client_with_engine):
    client, engine = client_with_engine
    client.post("/search", json={"query": "x", "top_k": 99})
    assert engine.calls[0][1] == 20


def test_search_without_engine_returns_503(monkeypatch):
    monkeypatch.setattr(api, "search_engine", None)
    resp = TestClient(api.app).post("/search", json={"query": "x"})
    assert resp.status_code == 503


def test_search_with_ai(monkeypatch, client_with_engine):
    client, engine = client_with_engine

    async def fake_enrich(query):
        return {
            "enriched_query": "infeccion intestinal por vibrio",
            "diagnosis": "Colera",
            "improvement_tips": ["Indica el agente"],
            "is_valid_medical_query": True,
            "processing_time_ms": 12.0,
        }

    monkeypatch.setattr(api, "enrich_query_with_ai", fake_enrich)
    resp = client.post("/search", json={"query": "diarrea", "use_ai": True})
    body = resp.json()
    assert body["used_ai"] is True
    assert body["assistant"]["diagnosis"] == "Colera"
    # El texto enriquecido se pasa al motor.
    assert engine.calls[0][2] == "infeccion intestinal por vibrio"


# ----------------------------------------------------------------------------
# /export-csv
# ----------------------------------------------------------------------------
def test_export_csv_success(client_with_engine):
    client, _ = client_with_engine
    resp = client.post("/export-csv", json=[{"code": "A00", "title": "Colera"}])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "code" in body["csv"]


def test_export_csv_empty(client_with_engine):
    client, _ = client_with_engine
    resp = client.post("/export-csv", json=[])
    assert resp.status_code == 200


# ----------------------------------------------------------------------------
# enrich_query_with_ai (httpx simulado)
# ----------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


def test_enrich_query_with_ai_success(monkeypatch):
    fake = _FakeAsyncClient(response=_FakeResp(200, {"enriched_query": "x"}))
    monkeypatch.setattr(api.httpx, "AsyncClient", fake)
    result = asyncio.run(api.enrich_query_with_ai("q"))
    assert result == {"enriched_query": "x"}


def test_enrich_query_with_ai_non_200(monkeypatch):
    fake = _FakeAsyncClient(response=_FakeResp(500, {}))
    monkeypatch.setattr(api.httpx, "AsyncClient", fake)
    assert asyncio.run(api.enrich_query_with_ai("q")) is None


def test_enrich_query_with_ai_exception(monkeypatch):
    fake = _FakeAsyncClient(raises=RuntimeError("boom"))
    monkeypatch.setattr(api.httpx, "AsyncClient", fake)
    assert asyncio.run(api.enrich_query_with_ai("q")) is None


def test_register_search_log_swallows_errors(monkeypatch):
    fake = _FakeAsyncClient(raises=RuntimeError("down"))
    monkeypatch.setattr(api.httpx, "AsyncClient", fake)
    # No debe lanzar excepción aunque el log-service falle.
    asyncio.run(
        api.register_search_log(
            session_id="s", user_id="u", query="q", top_k=5,
            results_count=0, ip_address="1.2.3.4", status="success",
        )
    )
