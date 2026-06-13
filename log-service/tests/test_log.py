"""Tests unitarios de los modelos Pydantic de ``log-service/main.py``.

Verifican los valores por defecto de los registros que se persisten en MongoDB
(sesiones, búsquedas y auditorías) y que la app FastAPI se importa.
"""
import main


def test_service_app_imports():
    assert hasattr(main, "app")


def test_search_record_defaults():
    record = main.SearchRecord(session_id="s", user_id="u", query="q")
    assert record.results_count == 0
    assert record.status == "success"
    assert record.used_ai_assistant is False
    assert record.ai_suggestions is None


def test_audit_record_defaults():
    record = main.AuditRecord(session_id="s", user_id="u", records_count=3)
    assert record.use_ai is False
    assert record.status == "success"
    assert record.total_time_ms is None


def test_session_model_optional_fields():
    session = main.Session(
        session_id="s1", user_id="u1", created_at="2025-01-01T00:00:00"
    )
    assert session.closed_at is None
    assert session.duration_seconds is None


def test_session_create_request():
    req = main.SessionCreateRequest(user_id="u1")
    assert req.ip_address is None
    assert req.user_agent is None
