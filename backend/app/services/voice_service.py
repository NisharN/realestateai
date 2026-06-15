"""Voice service: STT (Whisper) + TTS (Piper) + WebRTC handling."""
import os
import io
import logging
import subprocess
import tempfile
from typing import Optional, Dict, Any
import numpy as np

from groq import AsyncGroq

from app.config import get_settings

logger = logging.getLogger(__name__)


class VoiceService:
    """Handles speech-to-text and text-to-speech."""

    def __init__(self):
        self.settings = get_settings()
        self.groq_client = AsyncGroq(api_key=self.settings.GROQ_API_KEY) if self.settings.GROQ_API_KEY else None
        self.piper_path = self.settings.PIPER_MODEL_PATH

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Convert audio to text using Whisper.

        Args:
            audio_bytes: Raw audio data (WAV format preferred)
            language: 'en' or 'ar'
        """
        try:
            if not self.groq_client:
                logger.warning("Groq client not configured, using mock STT")
                return "[Mock transcription - configure GROQ_API_KEY]"

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # Groq Whisper API
            with open(tmp_path, "rb") as audio_file:
                response = await self.groq_client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=audio_file,
                    language="ar" if language == "ar" else "en"
                )

            # Cleanup
            os.unlink(tmp_path)

            return response.text

        except Exception as e:
            logger.error(f"STT error: {e}")
            return ""

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to speech using Piper TTS (free, local).

        Args:
            text: Text to synthesize
            language: 'en' or 'ar'
        """
        try:
            voice = self.settings.PIPER_VOICE_EN if language == "en" else self.settings.PIPER_VOICE_AR
            model_path = os.path.join(self.piper_path, f"{voice}.onnx")

            # Check if Piper model exists
            if not os.path.exists(model_path):
                logger.warning(f"Piper model not found at {model_path}, returning silent audio")
                # Return empty WAV header
                return self._generate_silent_wav()

            # Run Piper TTS
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                output_path = tmp_out.name

            process = await asyncio.create_subprocess_exec(
                "piper",
                "--model", model_path,
                "--output_file", output_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate(text.encode())

            if process.returncode != 0:
                logger.error(f"Piper error: {stderr.decode()}")
                return self._generate_silent_wav()

            # Read output
            with open(output_path, "rb") as f:
                audio = f.read()

            os.unlink(output_path)
            return audio

        except Exception as e:
            logger.error(f"TTS error: {e}")
            return self._generate_silent_wav()

    async def process_audio_stream(
        self,
        audio_bytes: bytes,
        lead_id: Optional[str] = None,
        language: str = "en"
    ) -> Dict[str, Any]:
        """Full pipeline: audio → text → AI response → audio."""
        # 1. STT
        user_text = await self.speech_to_text(audio_bytes, language)
        logger.info(f"User said: {user_text}")

        # 2. Get AI response (via lead message endpoint)
        # In production, call the conversation agent directly
        ai_response = f"I heard you say: {user_text}. Let me find properties for you."

        # 3. TTS
        audio_response = await self.text_to_speech(ai_response, language)

        return {
            "text": ai_response,
            "audio": audio_response,
            "user_text": user_text,
            "properties": []
        }

    def _generate_silent_wav(self) -> bytes:
        """Generate a minimal silent WAV file as fallback."""
        # 1 second of silence, 16kHz, mono, 16-bit
        sample_rate = 16000
        duration = 1
        num_samples = sample_rate * duration

        # WAV header + silent data
        import struct
        data = b"\x00\x00" * num_samples

        wav_header = struct.pack(
            "<4sI4s4sIHHIHH4sI",
            b"RIFF",
            36 + len(data),
            b"WAVE",
            b"fmt ",
            16,
            1,  # PCM
            1,  # Mono
            sample_rate,
            sample_rate * 2,
            2,
            16,
            b"data",
            len(data)
        )

        return wav_header + data


import asyncio  # For subprocess
