"""Voice conversation API routes."""
import logging
import base64
import io
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.database import get_db, LeadRepository
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/conversation/{lead_id}")
async def voice_conversation(websocket: WebSocket, lead_id: str, db=Depends(get_db)):
    """WebSocket endpoint for real-time voice conversation."""
    await websocket.accept()
    voice_service = VoiceService()

    try:
        # Get lead context
        lead_repo = LeadRepository(db)
        lead = await lead_repo.get_by_id(lead_id)

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

                # Process: STT → LLM → TTS
                result = await voice_service.process_audio_stream(
                    audio_data,
                    lead_id=lead_id,
                    language=lead.get("preferred_language", "en") if lead else "en"
                )

                # Send response
                await websocket.send_json({
                    "type": "audio",
                    "text": result["text"],
                    "audio": base64.b64encode(result["audio"]).decode("utf-8"),
                    "properties": result.get("properties", [])
                })

            elif message.get("type") == "text":
                # Text-only mode fallback
                from app.api.leads import send_message
                result = await send_message(
                    lead_id,
                    {"text": message["text"]},
                    db
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
async def synthesize_speech(text: str, language: str = "en"):
    """Text-to-speech endpoint."""
    voice_service = VoiceService()
    audio = await voice_service.text_to_speech(text, language)

    return StreamingResponse(
        io.BytesIO(audio),
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=speech.wav"}
    )
