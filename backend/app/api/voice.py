"""Voice conversation API routes."""
import logging
import base64
import io
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.database import get_db, get_lead_repository
from app.services.voice_service import VoiceService
from app.auth import AuthBackend, RequestContext, get_auth_backend, get_request_context
from app.api.leads import send_message

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/conversation/{lead_id}")
async def voice_conversation(
    websocket: WebSocket,
    lead_id: str,
    token: str,
    workspace_id: str,
    backend: AuthBackend = Depends(get_auth_backend),
    db=Depends(get_db),
):
    """WebSocket endpoint for real-time voice conversation."""
    context = await backend.authenticate(token, workspace_id)
    await websocket.accept()
    voice_service = VoiceService()

    try:
        # Get lead context
        lead_repo = get_lead_repository(context.workspace_id)
        lead = await lead_repo.get_by_id(lead_id)
        if not lead or not context.can_access_lead(lead):
            await websocket.close(code=4404)
            return

        # Send welcome message
        welcome = "Hello! I'm Ali, your Dubai property assistant. How can I help you today?"
        if lead and lead.get("preferred_language") == "ar":
            welcome = "مرحباً! أنا علي، مساعدك العقاري في دبي. كيف يمكنني مساعدتك اليوم؟"

        await websocket.send_json({
            "type": "text",
            "content": welcome
        })

        while True:
            # Receive audio data (base64 encoded)
            message = await websocket.receive_json()

            if message.get("type") == "audio":
                audio_data = base64.b64decode(message["data"])
                language = lead.get("preferred_language", "en") if lead else "en"

                # 1) Speech-to-text (Whisper via Groq, or a labeled
                #    placeholder if GROQ_API_KEY isn't configured).
                user_text = await voice_service.speech_to_text(audio_data, language)

                if not user_text or user_text.startswith("["):
                    ai_text = (
                        "I didn't catch that — please try again, or type your message."
                        if language != "ar"
                        else "لم أفهم ذلك — حاول مرة أخرى أو اكتب رسالتك."
                    )
                    matched_properties = []
                else:
                    # 2) Route the transcribed text through the SAME agent
                    #    pipeline text chat uses — this is the fix: voice
                    #    used to return a canned echo here instead of a
                    #    real AI response.
                    result = await send_message(lead_id, {"text": user_text}, context=context, db=db)
                    ai_text = result["response"]
                    matched_properties = result.get("matched_properties", [])

                # 3) Text-to-speech on the REAL response (Piper if
                #    installed, else gTTS, else silence).
                audio_response = await voice_service.text_to_speech(ai_text, language)

                await websocket.send_json({
                    "type": "audio",
                    "text": ai_text,
                    "user_text": user_text,
                    "audio": base64.b64encode(audio_response).decode("utf-8"),
                    "properties": matched_properties,
                })

            elif message.get("type") == "text":
                # Text-only mode fallback (same agent pipeline as above).
                result = await send_message(
                    lead_id,
                    {"text": message["text"]},
                    context=context,
                    db=db,
                )

                await websocket.send_json({
                    "type": "text",
                    "content": result["response"],
                    "properties": result.get("matched_properties", [])
                })

    except WebSocketDisconnect:
        logger.info(f"Voice conversation ended for lead {lead_id}")
    except Exception as e:
        logger.error(f"Voice websocket error: {e}")
        await websocket.close()


@router.post("/synthesize")
async def synthesize_speech(text: str, language: str = "en", context: RequestContext = Depends(get_request_context)):
    """Text-to-speech endpoint."""
    voice_service = VoiceService()
    audio = await voice_service.text_to_speech(text, language)

    return StreamingResponse(
        io.BytesIO(audio),
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=speech.wav"}
    )
