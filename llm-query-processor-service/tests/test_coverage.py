"""Tests de cobertura para ``llm-query-processor-service/main.py``.

Cubren las ramas que el resto de la suite no toca:

- Configuración a nivel de import: descubrimiento de credenciales JSON, y los
  dos ``raise ValueError`` (falta PROJECT_ID/LOCATION, falta plantilla de
  prompt). Se ejercitan cargando ``main.py`` como un módulo *fresco* bajo
  condiciones controladas (la cobertura se atribuye por ruta de archivo, así
  que cuenta para ``main.py``), sin perturbar el ``main`` ya importado.
- El ``lifespan`` de FastAPI (arranque con y sin conexión a Vertex AI).
- Las ramas ``except`` del parseo JSON en ``analyze_query`` / ``correct_query``
  / ``ai_search_assist`` y la normalización de ``improvement_tips`` no-lista.
"""
import glob as glob_mod
import importlib.util
import json

import pytest
from fastapi.testclient import TestClient

import main


# ---------------------------------------------------------------------------
# Carga de main.py como módulo fresco (para cubrir el código de import)
# ---------------------------------------------------------------------------
_COUNTER = [0]


def _load_fresh():
    _COUNTER[0] += 1
    spec = importlib.util.spec_from_file_location(
        f"main_fresh_{_COUNTER[0]}", main.__file__
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_import_with_credentials_file(monkeypatch, tmp_path):
    """Rama en la que se descubre un JSON de credenciales y se lee project_id."""
    cred = tmp_path / "creds.json"
    cred.write_text(json.dumps({"project_id": "cred-project"}))
    # El primer resultado no termina en ".json": el bucle debe saltarlo y seguir
    # hasta el JSON de credenciales válido (cubre la rama del `endswith`).
    monkeypatch.setattr(glob_mod, "glob", lambda *a, **k: [str(tmp_path / "notes.txt"), str(cred)])
    # monkeypatch registra la clave para restaurarla aunque el módulo la sobrescriba.
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "placeholder")

    mod = _load_fresh()

    assert mod.CREDENTIALS_FILE == str(cred)
    assert mod.PROJECT_ID == "cred-project"


def test_import_missing_project_id(monkeypatch):
    """Sin credenciales y sin ID -> PROJECT_ID vacío -> ValueError."""
    monkeypatch.setattr(glob_mod, "glob", lambda *a, **k: [])
    monkeypatch.delenv("ID", raising=False)

    with pytest.raises(ValueError):
        _load_fresh()


def test_import_missing_prompt_template(monkeypatch, tmp_path):
    """Un prompts.json al que le falta una plantilla obligatoria -> ValueError."""
    monkeypatch.setattr(glob_mod, "glob", lambda *a, **k: [])
    monkeypatch.setenv("ID", "test-project")
    bad_prompts = tmp_path / "prompts.json"
    bad_prompts.write_text(json.dumps({"analyze": "solo esta"}))
    monkeypatch.setenv("PROMPTS_FILE", str(bad_prompts))

    with pytest.raises(ValueError):
        _load_fresh()


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
def test_lifespan_startup_handles_vertex_error():
    """El modelo simulado lanza al generar: el startup lo captura y arranca igual."""
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "ok"


def test_lifespan_startup_success(monkeypatch):
    """Rama de conexión con Vertex AI establecida (generate_content no lanza)."""
    class _Resp:
        text = "ok"

    monkeypatch.setattr(main.model, "generate_content", lambda prompt: _Resp())
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Ramas except del parseo JSON
# ---------------------------------------------------------------------------
def test_analyze_query_except_on_invalid_json(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "texto {no valido} fin")
    result = main.analyze_query("q")
    assert result["primary_symptoms"] == []
    assert result["clinical_context"] == ""


def test_correct_query_except_on_invalid_json(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "texto {no valido} fin")
    result = main.correct_query("HTA")
    assert result["corrected_query"] == "HTA"
    assert result["is_valid_medical_query"] is True


def test_ai_search_assist_tips_not_list(monkeypatch):
    """improvement_tips que no es ni str ni list -> se normaliza a []."""
    monkeypatch.setattr(
        main,
        "call_gemini",
        lambda prompt: '{"diagnosis": "x", "enriched_query": "y", '
        '"improvement_tips": 123, "is_valid_medical_query": true}',
    )
    result = main.ai_search_assist("q")
    assert result["improvement_tips"] == []
    assert result["diagnosis"] == "x"


def test_ai_search_assist_except_on_invalid_json(monkeypatch):
    monkeypatch.setattr(main, "call_gemini", lambda prompt: "texto {no valido} fin")
    result = main.ai_search_assist("q")
    assert result == {
        "diagnosis": "",
        "enriched_query": "",
        "improvement_tips": [],
        "is_valid_medical_query": True,
    }
