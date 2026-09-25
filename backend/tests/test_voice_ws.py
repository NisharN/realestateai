"""Voice WebSocket v2 protocol: per-turn isolation, barge-in, low-confidence confirm, resume."""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api import voice as voice_api
from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.llm import gateway as llm_gateway
from app.modules.store import reset_memory
from app.services.voice_service import Transcript

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset():
    reset_memory()
    llm_gateway.reset_gateway()
    yield
    reset_memory()


def _lead() -> str:
    ws = get_settings().WORKSPACE_ID
    lead = asyncio.run(get_lead_repository(ws).create({"name": "Voice", "phone": "+971500000099", "source": "website"}))
    return lead["id"]


def _connect(lead_id: str, session_id: str = ""):
    q = f"?session_id={session_id}" if session_id else ""
    return client.websocket_connect(f"/api/v1/voice/conversation/{lead_id}{q}")


def _until(ws, kind: str, limit: int = 8) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_text_turn_returns_reply_with_spoken_text():
    lead_id = _lead()
    with _connect(lead_id) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["session_id"] and ready["resumed"] is False
        ws.send_json({"type": "text", "text": "buy a 2 bed apartment in dubai marina under AED 2,500,000", "turn_id": "t1"})
        assert _until(ws, "transcript")["text"].startswith("buy")
        reply = _until(ws, "reply")
        assert reply["turn_id"] == "t1" and reply["reply"] and reply["spoken_text"]
        assert "audio" not in reply  # no TTS engine → browser speaks spoken_text


def test_stt_failure_keeps_socket_open():
    lead_id = _lead()
    failed = Transcript(text="", provider=None, error="stt_timeout")
    with patch.object(voice_api.VoiceService, "transcribe", AsyncMock(return_value=failed)):
        with _connect(lead_id) as ws:
            ws.receive_json()
            ws.send_json({"type": "audio", "data": base64.b64encode(b"x").decode(), "turn_id": "a1"})
            reply = _until(ws, "reply")
            assert reply["fallbacks"] == ["stt"] and reply["stt_error"] == "stt_timeout" and reply["reply"]
            ws.send_json({"type": "text", "text": "hello", "turn_id": "a2"})
            assert _until(ws, "reply")["turn_id"] == "a2"


def test_low_confidence_transcript_is_confirmed_before_acting():
    lead_id = _lead()
    shaky = Transcript(text="buy a villa in arabian ranches", provider="groq", confidence=0.3)
    with patch.object(voice_api.VoiceService, "transcribe", AsyncMock(return_value=shaky)):
        with _connect(lead_id) as ws:
            ws.receive_json()
            ws.send_json({"type": "audio", "data": base64.b64encode(b"x").decode(), "turn_id": "c1"})
            confirm = _until(ws, "reply")
            assert "arabian ranches" in confirm["reply"].lower() and confirm["fallbacks"] == ["stt:low_confidence"]
            assert "move" not in confirm
            ws.send_json({"type": "text", "text": "yes", "turn_id": "c2"})
            reply = _until(ws, "reply")
            assert reply["user_text"] == "buy a villa in arabian ranches" and reply["move"]


def test_interrupt_cancels_inflight_turn():
    lead_id = _lead()

    async def slow(*_a, **_k):
        await asyncio.sleep(5)
        raise AssertionError("should have been cancelled")

    with patch.object(voice_api, "handle_turn", slow):
        with _connect(lead_id) as ws:
            ws.receive_json()
            ws.send_json({"type": "text", "text": "hello", "turn_id": "i1"})
            _until(ws, "transcript")
            ws.send_json({"type": "interrupt"})
            assert _until(ws, "cancelled")["turn_id"] == "i1"


def test_unknown_message_is_recoverable_error():
    lead_id = _lead()
    with _connect(lead_id) as ws:
        ws.receive_json()
        ws.send_json({"type": "bogus"})
        err = ws.receive_json()
        assert err["type"] == "error" and err["recoverable"] is True


def test_resume_replays_history():
    lead_id = _lead()
    with _connect(lead_id) as ws:
        ready = ws.receive_json()
        ws.send_json({"type": "text", "text": "I want to rent in JVC", "turn_id": "r1"})
        _until(ws, "reply")
    with _connect(lead_id, ready["session_id"]) as ws:
        resumed = ws.receive_json()
        assert resumed["resumed"] is True and resumed["session_id"] == ready["session_id"]
        roles = [m["role"] for m in resumed["history"]]
        assert roles == ["user", "assistant"]
        assert resumed["history"][0]["text"] == "I want to rent in JVC"
