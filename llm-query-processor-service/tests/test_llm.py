"""Tests unitarios de ``llm-query-processor-service/main.py``.

Cubren el mapeo de errores de ``call_gemini`` (429/403/500) y el parseo robusto
de las respuestas JSON del LLM en ``analyze_query``, ``correct_query`` y
``ai_search_assist``. Las llamadas reales al modelo se simulan con monkeypatch.
"""
import pytest
from fastapi import HTTPException

import main


# ----------------------------------------------------------------------------
# call_gemini: mapeo de errores
# ----------------------------------------------------------------------------
def test_call_gemini_success(monkeypatch):
    class _Resp:
        text = "  respuesta  "

    monkeypatch.setattr(main.model, "generate_content", lambda prompt: _Resp())
    assert main.call_gemini("x") == "respuesta"


def test_call_gemini_quota_maps_to_429(monkeypatch):
    def _raise(prompt):
        raise Exception("429 quota exceeded")

    monkeypatch.setattr(main.model, "generate_content", _raise)
    with pytest.raises(HTTPException) as exc:
        main.call_gemini("x")
    assert exc.value.status_code == 429


def test_call_gemini_permission_maps_to_403(monkeypatch):
    def _raise(prompt):
        raise Exception("403 permission denied")

    monkeypatch.setattr(main.model, "generate_content", _raise)
    with pytest.raises(HTTPException) as exc:
        main.call_gemini("x")
    assert exc.value.status_code == 403


def test_call_gemini_generic_maps_to_500(monkeypatch):
    def _raise(prompt):
        raise Exception("algo raro")

    monkeypatch.setattr(main.model, "generate_content", _raise)
    with pytest.raises(HTTPException) as exc:
        main.call_gemini("x")
    assert exc.value.status_code == 500


# ----------------------------------------------------------------------------
# analyze_query
# ----------------------------------------------------------------------------
def test_analyze_query_parses_json(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"primary_symptoms": ["tos"], "secondary_symptoms": [], '
        '"key_findings": [], "search_keywords": ["tos"], "clinical_context": "x"}',
    )
    result = main.analyze_query("tos")
    assert result["primary_symptoms"] == ["tos"]


def test_analyze_query_fallback_on_garbage(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "sin json")
    result = main.analyze_query("tos")
    assert result == {
        "primary_symptoms": [],
        "secondary_symptoms": [],
        "key_findings": [],
        "search_keywords": [],
        "clinical_context": "",
    }


# ----------------------------------------------------------------------------
# correct_query
# ----------------------------------------------------------------------------
def test_correct_query_parses(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"corrected_query": "hipertension arterial", '
        '"corrections": {"HTA": "hipertension arterial"}, "is_valid_medical_query": true}',
    )
    result = main.correct_query("HTA")
    assert result["corrected_query"] == "hipertension arterial"
    assert result["is_valid_medical_query"] is True


def test_correct_query_fallback_keeps_original(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "sin json")
    result = main.correct_query("HTA")
    assert result["corrected_query"] == "HTA"


# ----------------------------------------------------------------------------
# ai_search_assist
# ----------------------------------------------------------------------------
def test_ai_search_assist_parses_and_normalizes(monkeypatch):
    raw = (
        '{"diagnosis": " Neumonia ", "enriched_query": " infeccion pulmonar ", '
        '"improvement_tips": ["Indica lateralidad", "  ", 123], '
        '"is_valid_medical_query": true}'
    )
    monkeypatch.setattr(main, "call_gemini", lambda prompt: raw)
    result = main.ai_search_assist("tos con fiebre")
    assert result["diagnosis"] == "Neumonia"
    assert result["enriched_query"] == "infeccion pulmonar"
    assert result["improvement_tips"] == ["Indica lateralidad", "123"]
    assert result["is_valid_medical_query"] is True


def test_ai_search_assist_consejos_as_string(monkeypatch):
    raw = (
        '{"diagnosis": "x", "enriched_query": "y", '
        '"improvement_tips": "un consejo", "is_valid_medical_query": true}'
    )
    monkeypatch.setattr(main, "call_gemini", lambda prompt: raw)
    result = main.ai_search_assist("q")
    assert result["improvement_tips"] == ["un consejo"]


def test_ai_search_assist_fallback_on_garbage(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "sin json")
    result = main.ai_search_assist("q")
    assert result == {
        "diagnosis": "",
        "enriched_query": "",
        "improvement_tips": [],
        "is_valid_medical_query": True,
    }
