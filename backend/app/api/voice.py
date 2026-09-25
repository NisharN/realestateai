"""Voice conversation API routes.

The WebSocket shares the turn engine with chat/WhatsApp. Per-turn failures
(STT, engine, TTS) send a fallback reply and keep the socket open; the client
always receives ``reply`` text and may receive ``audio`` (real WAV) — when
``audio`` is absent the client should use browser speech synthesis.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.auth import AuthBackend, RequestContext, get_auth_backend, get_request_context
from app.database import get_lead_repository
from app.modules.conversation import templates
from app.modules.conversation.engine import handle_turn
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_S = 20.0


async def _send(ws: WebSocket, payload: dict) -> bool:
    try:
        await ws.send_json(payload)
        return True
    except Exception as exc:  # socket gone
        logger.info("voice send failed: %s", exc)
        return False


@router.websocket("/conversation/{lead_id}")
async def voice_conversation(
    websocket: WebSocket,
    lead_id: str,
    token: str = "",
    workspace_id: str = "",
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

    lead_repo = get_lead_repository(context.workspace_id)
    lead = await lead_repo.get_by_id(lead_id)
    if not lead or not context.can_access_lead(lead):
        await websocket.close(code=4404)
        return
    language = lead.get("preferred_language", "en") or "en"

    await _send(
        websocket,
        {
            "type": "ready",
            "session_id": uuid.uuid4().hex,
            "tts": voice.tts_available(language),
            "heartbeat_s": HEARTBEAT_S,
            "reply": templates.render("greeting", language, {"brokerage": "our brokerage"}),
        },
    )

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
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
                continue

            turn_id = message.get("turn_id") or uuid.uuid4().hex
            user_text = ""
            stt_error: str | None = None
            try:
                if kind == "audio":
                    audio = base64.b64decode(message.get("data") or "")
                    transcript = await voice.transcribe(audio, language)
                    if transcript.ok:
                        user_text = transcript.text
                    else:
                        stt_error = transcript.error or "stt_failed"
                elif kind == "text":
                    user_text = (message.get("text") or "").strip()
                else:
                    await _send(websocket, {"type": "error", "turn_id": turn_id, "code": "unknown_message_type", "recoverable": True})
                    continue

                if not user_text:
                    reply = templates.render("stt_failed", language, {})
                    await _send(websocket, {"type": "reply", "turn_id": turn_id, "reply": reply, "user_text": "", "stt_error": stt_error, "fallbacks": ["stt"]})
                    continue

                result = await handle_turn(
                    lead_id,
                    user_text,
                    workspace_id=context.workspace_id,
                    channel="voice",
                    idempotency_key=f"voice:{turn_id}",
                )
                language = result.language or language
                payload = {
                    "type": "reply",
                    "turn_id": turn_id,
                    "user_text": user_text,
                    "reply": result.reply,
                    "move": result.move,
                    "stage": result.stage,
                    "score": result.score,
                    "properties": result.cards,
                    "area": result.area,
                    "handoff_id": result.handoff_id,
                    "ended": result.ended,
                    "fallbacks": result.fallbacks,
                }
                if kind == "audio" or message.get("want_audio"):
                    wav = await voice.text_to_speech(result.reply, language)
                    if wav:
                        payload["audio"] = base64.b64encode(wav).decode("ascii")
                        payload["audio_format"] = "audio/wav"
                if not await _send(websocket, payload):
                    break
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                logger.exception("voice turn failed for lead %s: %s", lead_id, exc)
                reply = templates.render("error_fallback", language, {})
                if not await _send(websocket, {"type": "reply", "turn_id": turn_id, "user_text": user_text, "reply": reply, "fallbacks": ["template:exception"]}):
                    break
    except WebSocketDisconnect:
        logger.info("voice conversation ended for lead %s", lead_id)
    except Exception as exc:
        logger.error("voice websocket error: %s", exc)
    finally:
        hb.cancel()


@router.post("/synthesize")
async def synthesize_speech(text: str, language: str = "en", context: RequestContext = Depends(get_request_context)):
    audio = await VoiceService().text_to_speech(text, language)
    if audio is None:
        return Response(status_code=204, headers={"X-TTS-Fallback": "browser"})
    return Response(content=io.BytesIO(audio).getvalue(), media_type="audio/wav")
