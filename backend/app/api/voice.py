"""Voice conversation API routes (architecture §11).

The WebSocket is only a different input/output around the shared turn engine.
Per-turn failures (STT, engine, TTS) send a template reply and keep the socket
open. Protocol (client → server):

    {type: audio, data: <b64>, mime?, turn_id?}  one utterance (VAD/PTT end)
    {type: text, text, turn_id?}             typed fallback
    {type: interrupt}                        barge-in: cancel the in-flight turn
    {type: ping|pong}

Server → client: ``ready`` (with ``config`` and, when resuming a ``session_id``, ``history``),
``transcript``, ``thinking`` (turn > 1.2 s), ``reply`` (+ optional WAV
``audio``; when absent the browser speaks ``spoken_text``), ``cancelled``,
``error``, ``ping``.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.auth import AuthBackend, RequestContext, get_auth_backend, get_request_context
from app.config import get_settings
from app.database import get_lead_repository
from app.modules.conversation import templates
from app.modules.conversation.engine import TurnResult, handle_turn
from app.modules.conversation.repository import ConversationRepo
from app.modules.voice.config import VoiceConfig, build_voice_config
from app.modules.voice.speakify import speakify
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_TTS_CHARS = 600


def max_audio_b64_chars(max_audio_bytes: int) -> int:
    return max_audio_bytes * 4 // 3 + 4


MAX_AUDIO_B64_CHARS = max_audio_b64_chars(get_settings().VOICE_MAX_AUDIO_BYTES)
MAX_TEXT_CHARS = get_settings().VOICE_MAX_TEXT_CHARS
YES_WORDS = {"yes", "yeah", "yep", "correct", "right", "نعم", "ايوه", "أيوه", "صح"}


async def _send(ws: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await ws.send_json(payload)
        return True
    except Exception as exc:  # socket gone
        logger.info("voice send failed: %s", exc)
        return False


class VoiceSession:
    """One socket: serialises turns, supports barge-in and resume."""

    def __init__(
        self, ws: WebSocket, lead_id: str, workspace_id: str, language: str, voice: VoiceService, config: VoiceConfig
    ) -> None:
        self.ws = ws
        self.lead_id = lead_id
        self.workspace_id = workspace_id
        self.language = language
        self.voice = voice
        self.config = config
        self.current: asyncio.Task[None] | None = None
        self.pending_confirm: str | None = None  # low-confidence transcript awaiting "yes"
        self.drains: set[asyncio.Task[None]] = set()

    async def interrupt(self) -> None:
        task = self.current
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def start_turn(self, message: dict[str, Any]) -> None:
        self.current = asyncio.create_task(self._turn(message))

    async def _turn(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        turn_id = str(message.get("turn_id") or uuid.uuid4().hex)
        user_text = ""
        stt_error: str | None = None
        confidence: float | None = None
        engine: asyncio.Task[TurnResult] | None = None
        try:
            if kind == "audio":
                audio = base64.b64decode(message.get("data") or "")
                transcript = await self.voice.transcribe(audio, self.language, mime=str(message.get("mime") or ""))
                if transcript.ok:
                    user_text, confidence = transcript.text, transcript.confidence
                else:
                    stt_error = transcript.error or "stt_failed"
            else:
                user_text = str(message.get("text") or "").strip()

            if not user_text:
                await self._reply_template(turn_id, "stt_failed", "", stt_error=stt_error, fallbacks=["stt"])
                return

            await _send(self.ws, {"type": "transcript", "turn_id": turn_id, "text": user_text, "confidence": confidence})

            # Low-confidence STT: repeat back once; "yes" accepts, anything else replaces it.
            if self.pending_confirm is not None:
                if user_text.strip().lower().rstrip(".!") in YES_WORDS:
                    user_text = self.pending_confirm
                self.pending_confirm = None
            elif kind == "audio" and confidence is not None and confidence < self.config.low_confidence:
                self.pending_confirm = user_text
                await self._reply_template(turn_id, "confirm_transcript", user_text, transcript=user_text, fallbacks=["stt:low_confidence"])
                return

            thinking = asyncio.create_task(self._thinking(turn_id))
            # The engine persists state and may create a handoff, so a barge-in
            # must never abandon it half-way: shield it and always deliver its result.
            engine = asyncio.create_task(
                handle_turn(
                    self.lead_id,
                    user_text,
                    workspace_id=self.workspace_id,
                    channel="voice",
                    idempotency_key=f"voice:{turn_id}",
                )
            )
            try:
                result = await asyncio.shield(engine)
            finally:
                thinking.cancel()
            payload = self._reply_payload(turn_id, user_text, result)
            if kind == "audio" or message.get("want_audio"):
                wav = await self.voice.text_to_speech(payload["spoken_text"], self.language)
                if wav:
                    payload["audio"] = base64.b64encode(wav).decode("ascii")
                    payload["audio_format"] = "audio/wav"
            await _send(self.ws, payload)
        except asyncio.CancelledError:
            await _send(self.ws, {"type": "cancelled", "turn_id": turn_id})
            if engine is not None:
                drain = asyncio.create_task(self._deliver_committed(turn_id, user_text, engine))
                self.drains.add(drain)
                drain.add_done_callback(self.drains.discard)
            raise
        except Exception as exc:
            logger.exception("voice turn failed for lead %s: %s", self.lead_id, exc)
            await self._reply_template(turn_id, "error_fallback", user_text, fallbacks=["template:exception"])

    async def _deliver_committed(self, turn_id: str, user_text: str, engine: asyncio.Task[TurnResult]) -> None:
        """After a barge-in the engine still finishes; its persisted outcome
        (state, handoff) is delivered as a text-only reply rather than hidden."""
        try:
            result = await asyncio.shield(engine)
        except asyncio.CancelledError:
            # Socket closed; the engine keeps running so the turn is never
            # left half-persisted, and the outcome is replayed on resume.
            raise
        except Exception as exc:
            logger.warning("voice engine failed after interrupt for lead %s: %s", self.lead_id, exc)
            return
        payload = self._reply_payload(turn_id, user_text, result)
        payload["interrupted"] = True
        await _send(self.ws, payload)

    async def close(self) -> None:
        await self.interrupt()
        for task in self.drains:
            task.cancel()

    def _reply_payload(self, turn_id: str, user_text: str, result: TurnResult) -> dict[str, Any]:
        self.language = result.language or self.language
        return {
            "type": "reply",
            "turn_id": turn_id,
            "user_text": user_text,
            "reply": result.reply,
            "language": self.language,
            "spoken_text": speakify(result.reply, self.language),
            "move": result.move,
            "stage": result.stage,
            "score": result.score,
            "properties": result.cards,
            "area": result.area,
            "handoff_id": result.handoff_id,
            "ended": result.ended,
            "fallbacks": result.fallbacks,
        }

    async def _thinking(self, turn_id: str) -> None:
        await asyncio.sleep(self.config.thinking_after_s)
        await _send(self.ws, {"type": "thinking", "turn_id": turn_id})

    async def _reply_template(
        self, turn_id: str, key: str, user_text: str, *, fallbacks: list[str], stt_error: str | None = None, **facts: Any
    ) -> None:
        reply = templates.render(key, self.language, facts)
        payload: dict[str, Any] = {
            "type": "reply", "turn_id": turn_id, "user_text": user_text, "reply": reply,
            "language": self.language, "spoken_text": speakify(reply, self.language), "fallbacks": fallbacks,
        }
        if stt_error:
            payload["stt_error"] = stt_error
        await _send(self.ws, payload)


@router.websocket("/conversation/{lead_id}")
async def voice_conversation(
    websocket: WebSocket,
    lead_id: str,
    token: str = "",
    workspace_id: str = "",
    session_id: str = "",
    backend: AuthBackend = Depends(get_auth_backend),
):
    try:
        context = await backend.authenticate(token)
    except Exception as exc:
        logger.info("voice auth failed: %s", exc)
        await websocket.close(code=4401)
        return
    if workspace_id and workspace_id != context.workspace_id:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    voice = VoiceService()
    settings = get_settings()

    lead_repo = get_lead_repository(context.workspace_id)
    lead = await lead_repo.get_by_id(lead_id)
    if not lead or not context.can_access_lead(lead):
        await websocket.close(code=4404)
        return
    language = lead.get("preferred_language", "en") or "en"
    config = build_voice_config(voice, language)
    max_audio_b64 = max_audio_b64_chars(config.max_audio_bytes)

    ready: dict[str, Any] = {
        "type": "ready",
        "session_id": session_id or uuid.uuid4().hex,
        "resumed": bool(session_id),
        "tts": config.providers.tts == "piper",
        "heartbeat_s": settings.VOICE_HEARTBEAT_S,
        "config": config.model_dump(),
        "reply": templates.render("greeting", language, {"brokerage": "our brokerage"}),
    }
    if session_id:
        # Resume: the state is persisted after every turn, so only the transcript is replayed.
        history = await ConversationRepo(context.workspace_id).history(lead_id, limit=20)
        ready["history"] = [{"role": m.get("role"), "text": m.get("text"), "created_at": m.get("created_at")} for m in history]
    await _send(websocket, ready)

    session = VoiceSession(websocket, lead_id, context.workspace_id, language, voice, config)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.VOICE_HEARTBEAT_S)
            if not await _send(websocket, {"type": "ping"}):
                return

    hb = asyncio.create_task(heartbeat())
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind in {"ping", "pong"}:
                if kind == "ping":
                    await _send(websocket, {"type": "pong"})
            elif kind == "interrupt":
                await session.interrupt()
            elif kind == "audio" and len(message.get("data") or "") > max_audio_b64:
                await _send(websocket, {"type": "error", "turn_id": message.get("turn_id"), "code": "audio_too_large", "recoverable": True, "max_bytes": config.max_audio_bytes})
            elif kind == "text" and len(message.get("text") or "") > config.max_text_chars:
                await _send(websocket, {"type": "error", "turn_id": message.get("turn_id"), "code": "text_too_long", "recoverable": True, "max_chars": config.max_text_chars})
            elif kind in {"audio", "text"}:
                await session.interrupt()  # a new utterance always wins over an in-flight reply
                session.start_turn(message)
            else:
                await _send(websocket, {"type": "error", "turn_id": message.get("turn_id"), "code": "unknown_message_type", "recoverable": True})
    except WebSocketDisconnect:
        logger.info("voice conversation ended for lead %s", lead_id)
    except Exception as exc:
        logger.error("voice websocket error: %s", exc)
    finally:
        hb.cancel()
        await session.close()


@router.get("/config", response_model=VoiceConfig)
async def voice_config(
    language: str = Query("en", max_length=8),
    context: RequestContext = Depends(get_request_context),
):
    """Effective voice configuration and provider availability for this deployment."""
    return build_voice_config(VoiceService(), language)


@router.post("/synthesize")
async def synthesize_speech(
    text: str = Query(..., min_length=1, max_length=MAX_TTS_CHARS),
    language: str = Query("en", max_length=8),
    context: RequestContext = Depends(get_request_context),
):
    audio = await VoiceService().text_to_speech(speakify(text, language), language)
    if audio is None:
        return Response(status_code=204, headers={"X-TTS-Fallback": "browser"})
    return Response(content=io.BytesIO(audio).getvalue(), media_type="audio/wav")
