"""Tests de los endpoints de ``llm-query-processor-service/main.py``.

Se ejercitan los endpoints con ``TestClient`` simulando ``call_gemini`` para no
llamar a Vertex AI. Cubren ``/health``, ``/analyze``, ``/correct``,
``/process`` y ``/ai-search``.
"""
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


def test_health():
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["service"] == "llm-query-processor"


def test_analyze_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"primary_symptoms": ["tos"], "secondary_symptoms": [], '
        '"key_findings": [], "search_keywords": ["tos"], "clinical_context": ""}',
    )
    resp = client.post("/analyze", json={"query": "tos"})
    assert resp.status_code == 200
    assert resp.json()["primary_symptoms"] == ["tos"]


def test_correct_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"corrected_query": "hipertension arterial", '
        '"corrections": {}, "is_valid_medical_query": true}',
    )
    resp = client.post("/correct", json={"query": "HTA"})
    assert resp.json()["corrected_query"] == "hipertension arterial"


def test_process_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"corrected_query": "fiebre", "corrections": {}, '
        '"is_valid_medical_query": true, "primary_symptoms": [], '
        '"secondary_symptoms": [], "key_findings": [], "search_keywords": [], '
        '"clinical_context": ""}',
    )
    resp = client.post("/process", json={"query": "fiebre"})
    body = resp.json()
    assert body["original_query"] == "fiebre"
    assert "analysis" in body
    assert "processing_time_ms" in body


def test_ai_search_endpoint(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"diagnostico": "Neumonia", "enriched_query": "infeccion pulmonar", '
        '"consejos_mejora": ["Indica lateralidad"], "is_valid_medical_query": true}',
    )
    resp = client.post("/ai-search", json={"query": "tos con fiebre"})
    body = resp.json()
    assert body["diagnostico"] == "Neumonia"
    assert body["enriched_query"] == "infeccion pulmonar"
    assert body["consejos_mejora"] == ["Indica lateralidad"]
    assert "processing_time_ms" in body
