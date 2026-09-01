"""Voice service: STT (Whisper via Groq) + TTS (Piper if installed, else gTTS).

Falls back gracefully:
- If GROQ_API_KEY missing → mock STT
- If piper binary not on PATH → gTTS (cloud, free, no key) or silent WAV
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import tempfile
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class VoiceService:
    """Handles speech-to-text and text-to-speech with graceful fallbacks."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.groq_client = None
        self.huggingface_client = None
        try:
            if self.settings.GROQ_API_KEY:
                from groq import AsyncGroq
                self.groq_client = AsyncGroq(api_key=self.settings.GROQ_API_KEY)
        except Exception as exc:  # pragma: no cover
            logger.warning("Groq client init failed: %s", exc)

        try:
            if self.settings.HUGGING_FACE_API_KEY:
                from huggingface_hub import AsyncInferenceClient

                self.huggingface_client = AsyncInferenceClient(
                    token=self.settings.HUGGING_FACE_API_KEY
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("Hugging Face client init failed: %s", exc)

        self.piper_path = self.settings.PIPER_MODEL_PATH
        self.piper_binary = shutil.which("piper")

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe with Groq first and Hugging Face as fallback."""
        if not audio_bytes:
            return ""

        if self.groq_client:
            tmp_path = ""
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name

                with open(tmp_path, "rb") as audio_file:
                    response = await self.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        language="ar" if language == "ar" else "en",
                    )
                return response.text or ""
            except Exception as exc:
                logger.warning("Groq STT failed; trying fallback: %s", exc)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        if self.huggingface_client:
            try:
                response = await self.huggingface_client.automatic_speech_recognition(
                    audio_bytes,
                    model=self.settings.HUGGING_FACE_STT_MODEL,
                )
                if isinstance(response, str):
                    return response
                return response.text or ""
            except Exception as exc:
                logger.error("Hugging Face STT failed: %s", exc)
                return ""

        return "[STT unavailable - configure GROQ_API_KEY or HUGGING_FACE_API_KEY]"

    async def text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Convert text to speech. Piper → gTTS → silent WAV."""
        if not text:
            return self._silent_wav()

        # 1) Try Piper if binary + model are present.
        try:
            voice = (
                self.settings.PIPER_VOICE_EN
                if language != "ar"
                else self.settings.PIPER_VOICE_AR
            )
            model_path = os.path.join(self.piper_path, f"{voice}.onnx")
            if self.piper_binary and os.path.exists(model_path):
                return await self._piper_synthesize(text, model_path)
        except Exception as exc:
            logger.warning("Piper TTS unavailable, falling back: %s", exc)

        # 2) Fall back to gTTS (cloud, free, no key needed).
        try:
            return await self._gtts_synthesize(text, language)
        except Exception as exc:
            logger.warning("gTTS unavailable, returning silence: %s", exc)
            return self._silent_wav()

    async def _piper_synthesize(self, text: str, model_path: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
            output_path = tmp_out.name

        process = await asyncio.create_subprocess_exec(
            self.piper_binary,
            "--model",
            model_path,
            "--output_file",
            output_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(text.encode())
        if process.returncode != 0:
            os.unlink(output_path)
            raise RuntimeError(stderr.decode() or "piper failed")

        with open(output_path, "rb") as f:
            audio = f.read()
        os.unlink(output_path)
        return audio

    async def _gtts_synthesize(self, text: str, language: str) -> bytes:
        from gtts import gTTS  # type: ignore

        loop = asyncio.get_running_loop()

        def _build() -> bytes:
            buf = io.BytesIO()
            tts = gTTS(text=text, lang="ar" if language == "ar" else "en")
            tts.write_to_fp(buf)
            return buf.getvalue()

        mp3_bytes = await loop.run_in_executor(None, _build)

        # gTTS returns MP3 — convert to a minimal WAV by writing raw header.
        # Most browsers won't decode MP3 via simple <audio src="data:audio/wav">
        # so we wrap the MP3 with a WAV header that downstream clients may ignore
        # and rely on the file extension as a hint. For streaming use mp3 directly.
        return self._wrap_as_wav(mp3_bytes)

    @staticmethod
    def _wrap_as_wav(payload: bytes) -> bytes:
        """Wrap arbitrary bytes in a 16 kHz mono 16-bit PCM header.

        Clients should detect format by content-type, not the wrapper. This is
        purely so the streaming response always returns bytes that look like
        WAV; the body itself is the gTTS MP3.
        """
        sample_rate = 16000
        data = payload  # raw gTTS MP3
        bits_per_sample = 16
        num_channels = 1
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8

        header = (
            b"RIFF"
            + (36 + len(data)).to_bytes(4, "little")  # RIFF size
            + b"WAVE"
            + b"fmt "
            + (16).to_bytes(4, "little")              # fmt chunk size
            + (1).to_bytes(2, "little")                # PCM
            + num_channels.to_bytes(2, "little")
            + sample_rate.to_bytes(4, "little")
            + byte_rate.to_bytes(4, "little")
            + block_align.to_bytes(2, "little")
            + bits_per_sample.to_bytes(2, "little")
            + b"data"
            + len(data).to_bytes(4, "little")
        )
        return header + data

    # NOTE: audio → AI response routing lives in app/api/voice.py, which
    # calls speech_to_text() below, then the real agent pipeline via
    # app.api.leads.send_message(), then text_to_speech() below. This
    # class intentionally only exposes STT/TTS primitives now — the
    # previous process_audio_stream() here returned a canned echo
    # instead of a real AI response, which was a known POC gap. Fixed by
    # removing the shortcut rather than patching it, so there's no
    # lingering fake path to accidentally call.

    @staticmethod
    def _silent_wav(duration: float = 1.0, sample_rate: int = 16000) -> bytes:
        num_samples = int(sample_rate * duration)
        data = b"\x00\x00" * num_samples
        return VoiceService._wrap_as_wav(data)
