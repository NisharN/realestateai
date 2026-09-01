from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.voice_service import VoiceService


@pytest.mark.asyncio
async def test_speech_to_text_prefers_groq():
    service = VoiceService.__new__(VoiceService)
    service.groq_client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(text="Dubai Marina"))
            )
        )
    )
    service.huggingface_client = SimpleNamespace(
        automatic_speech_recognition=AsyncMock()
    )
    service.settings = SimpleNamespace(HUGGING_FACE_STT_MODEL="unused")

    result = await service.speech_to_text(b"audio", "en")

    assert result == "Dubai Marina"
    service.huggingface_client.automatic_speech_recognition.assert_not_awaited()


@pytest.mark.asyncio
async def test_speech_to_text_falls_back_to_hugging_face_when_groq_fails():
    service = VoiceService.__new__(VoiceService)
    service.groq_client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=AsyncMock(side_effect=RuntimeError("provider unavailable"))
            )
        )
    )
    service.huggingface_client = SimpleNamespace(
        automatic_speech_recognition=AsyncMock(
            return_value=SimpleNamespace(text="مرسى دبي")
        )
    )
    service.settings = SimpleNamespace(
        HUGGING_FACE_STT_MODEL="openai/whisper-large-v3-turbo"
    )

    result = await service.speech_to_text(b"audio", "ar")

    assert result == "مرسى دبي"
    service.huggingface_client.automatic_speech_recognition.assert_awaited_once_with(
        b"audio", model="openai/whisper-large-v3-turbo"
    )


@pytest.mark.asyncio
async def test_speech_to_text_reports_unavailable_without_any_provider():
    service = VoiceService.__new__(VoiceService)
    service.groq_client = None
    service.huggingface_client = None
    service.settings = SimpleNamespace(
        HUGGING_FACE_STT_MODEL="openai/whisper-large-v3-turbo"
    )

    result = await service.speech_to_text(b"audio", "en")

    assert result == "[STT unavailable - configure GROQ_API_KEY or HUGGING_FACE_API_KEY]"


@pytest.mark.asyncio
async def test_speech_to_text_does_not_call_provider_for_empty_audio():
    service = VoiceService.__new__(VoiceService)
    service.groq_client = SimpleNamespace()
    service.huggingface_client = SimpleNamespace()
    service.settings = SimpleNamespace(
        HUGGING_FACE_STT_MODEL="openai/whisper-large-v3-turbo"
    )

    assert await service.speech_to_text(b"", "en") == ""
