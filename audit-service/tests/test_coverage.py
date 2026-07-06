"""Tests de cobertura de helpers asíncronos internos de ``audit-service/main.py``.

Ejercitan directamente (sin pasar por la pila HTTP) las ramas que no cubren los
tests de endpoint:

- ``_emit_audit_stream``: desconexión del cliente, timeout de la cola de
  progreso y drenaje de eventos residuales antes de emitir 'complete'.
- ``_log_audit_to_service``: salida temprana sin usuario y absorción silenciosa
  de errores de red hacia el log-service.
"""
import asyncio
from datetime import datetime, timezone

import main


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------
class _Finding:
    def __init__(self):
        self.patient_id = "PAT0000"
        self.diagnosis_text = "tos"
        self.assigned_code = "A00.0"
        self.suggested_code = "A00.0"
        self.discrepancy_type = main.DiscrepancyType.CORRECT
        self.confidence_score = 0.9
        self.match_score = 1.0
        self.explanation = "ok"
        self.alternative_codes = []


class _Report:
    def __init__(self):
        self.audit_id = "aud-1"
        self.timestamp = datetime.now(timezone.utc)
        self.total_records = 1
        self.total_correct = 1
        self.total_partial_match = 0
        self.total_mismatch = 0
        self.conformity_percentage = 100.0
        self.total_time_ms = 12.345
        self.findings = [_Finding()]


class _FakeReq:
    def __init__(self, disconnected):
        self._disconnected = disconnected

    async def is_disconnected(self):
        return self._disconnected


class _DoneTask:
    """audit_task ya finalizado."""

    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class _FlipTask:
    """done() devuelve False la primera vez y True en las siguientes."""

    def __init__(self, result):
        self._n = 0
        self._result = result

    def done(self):
        self._n += 1
        return self._n > 1

    def result(self):
        return self._result


# ---------------------------------------------------------------------------
# _emit_audit_stream
# ---------------------------------------------------------------------------
def test_emit_stream_stops_on_disconnect():
    async def run():
        q = asyncio.Queue()
        gen = main._emit_audit_stream(_FakeReq(True), _FlipTask(_Report()), q, 5)
        return [chunk async for chunk in gen]

    assert asyncio.run(run()) == []


def test_emit_stream_timeout_continues_then_completes():
    async def run():
        q = asyncio.Queue()  # vacía -> wait_for hace timeout -> continue
        gen = main._emit_audit_stream(_FakeReq(False), _FlipTask(_Report()), q, 5)
        return [chunk async for chunk in gen]

    chunks = asyncio.run(run())
    assert any('"type": "complete"' in c for c in chunks)


def test_emit_stream_drains_residual_events():
    async def run():
        q = asyncio.Queue()
        q.put_nowait({"type": "progress", "current": 1, "total": 1})
        gen = main._emit_audit_stream(_FakeReq(False), _DoneTask(_Report()), q, 5)
        return [chunk async for chunk in gen]

    chunks = asyncio.run(run())
    assert any('"type": "progress"' in c for c in chunks)
    assert any('"type": "complete"' in c for c in chunks)


# ---------------------------------------------------------------------------
# _log_audit_to_service
# ---------------------------------------------------------------------------
def test_log_audit_no_user_returns_early():
    # current_user vacío -> return inmediato, sin tocar httpx.
    asyncio.run(main._log_audit_to_service(_Report(), "", 5, False))


def test_log_audit_swallows_errors(monkeypatch):
    class BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("log-service caído")

    monkeypatch.setattr(main.httpx, "AsyncClient", BoomClient)
    # No debe propagar: el error se registra como warning y se ignora.
    asyncio.run(main._log_audit_to_service(_Report(), "u@test.com", 5, False))
