"""Voice service: STT (Whisper via Groq, Hugging Face fallback) + TTS (Piper).

Every provider call is bounded by a timeout. When no TTS engine is available the
service returns ``None`` so the client falls back to browser speech synthesis —
we never ship an MP3 disguised as WAV.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass

from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Transcript:
    text: str
    provider: str | None  # None when every provider failed / none configured
    error: str | None = None
    confidence: float | None = None  # 0..1 when the provider reports it

    @property
    def ok(self) -> bool:
        return bool(self.text.strip()) and self.provider is not None


def _whisper_confidence(response: object) -> float | None:
    """Mean segment avg_logprob (≈ -1..0) mapped onto 0..1; None when absent."""
    if not isinstance(response, BaseModel):
        return None
    segments = response.model_dump().get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    probs: list[float] = []
    for seg in segments:
        lp = seg.get("avg_logprob") if isinstance(seg, dict) else None
        if isinstance(lp, (int, float)):
            probs.append(float(lp))
    if not probs:
        return None
    mean = sum(probs) / len(probs)
    return max(0.0, min(1.0, 1.0 + mean))


class VoiceService:
    """STT/TTS primitives with timeouts and graceful degradation."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.last_confidence: float | None = None
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

                self.huggingface_client = AsyncInferenceClient(token=self.settings.HUGGING_FACE_API_KEY)
        except Exception as exc:  # pragma: no cover
            logger.warning("Hugging Face client init failed: %s", exc)

        self.piper_path = self.settings.PIPER_MODEL_PATH
        self.piper_binary = shutil.which("piper")

    # ------------------------------------------------------------------ STT
    async def transcribe(self, audio_bytes: bytes, language: str = "en") -> Transcript:
        if not audio_bytes:
            return Transcript(text="", provider=None, error="empty audio")
        timeout = self.settings.STT_TIMEOUT_S
        last_error: str | None = None

        if self.groq_client:
            try:
                self.last_confidence = None
                text = await asyncio.wait_for(self._groq_stt(audio_bytes, language), timeout=timeout)
                return Transcript(text=text, provider="groq", confidence=self.last_confidence)
            except Exception as exc:
                last_error = f"groq: {exc}"
                logger.warning("Groq STT failed; trying fallback: %s", exc)

        if self.huggingface_client:
            try:
                text = await asyncio.wait_for(self._hf_stt(audio_bytes), timeout=timeout)
                return Transcript(text=text, provider="huggingface")
            except Exception as exc:
                last_error = f"huggingface: {exc}"
                logger.warning("Hugging Face STT failed: %s", exc)

        return Transcript(text="", provider=None, error=last_error or "no STT provider configured")

    async def speech_to_text(self, audio_bytes: bytes, language: str = "en") -> str:
        """Backwards-compatible helper; returns '' when transcription failed."""
        return (await self.transcribe(audio_bytes, language)).text

    async def _groq_stt(self, audio_bytes: bytes, language: str) -> str:
        assert self.groq_client is not None
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
                    response_format="verbose_json",
                )
            self.last_confidence = _whisper_confidence(response)
            return response.text or ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def _hf_stt(self, audio_bytes: bytes) -> str:
        assert self.huggingface_client is not None
        response = await self.huggingface_client.automatic_speech_recognition(
            audio_bytes, model=self.settings.HUGGING_FACE_STT_MODEL
        )
        if isinstance(response, str):
            return response
        return response.text or ""

    # ------------------------------------------------------------------ TTS
    def tts_available(self, language: str = "en") -> bool:
        return self._piper_model(language) is not None

    def _piper_model(self, language: str) -> str | None:
        voice = self.settings.PIPER_VOICE_EN if language != "ar" else self.settings.PIPER_VOICE_AR
        model_path = os.path.join(self.piper_path, f"{voice}.onnx")
        if self.piper_binary and os.path.exists(model_path):
            return model_path
        return None

    async def text_to_speech(self, text: str, language: str = "en") -> bytes | None:
        """Return real WAV bytes from Piper, or ``None`` if no engine is available.

        Callers must treat ``None`` as "use browser speech synthesis".
        """
        if not text:
            return None
        model_path = self._piper_model(language)
        if model_path is None:
            return None
        try:
            return await asyncio.wait_for(self._piper_synthesize(text, model_path), timeout=self.settings.TTS_TIMEOUT_S)
        except Exception as exc:
            logger.warning("Piper TTS failed: %s", exc)
            return None

    async def _piper_synthesize(self, text: str, model_path: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
            output_path = tmp_out.name
        try:
            process = await asyncio.create_subprocess_exec(
                self.piper_binary or "piper",
                "--model",
                model_path,
                "--output_file",
                output_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await process.communicate(text.encode())
            except asyncio.CancelledError:
                process.kill()
                raise
            if process.returncode != 0:
                raise RuntimeError(stderr.decode() or "piper failed")
            with open(output_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    @staticmethod
    def silent_wav(duration: float = 0.2, sample_rate: int = 16000) -> bytes:
        """A genuine PCM WAV of silence (used only for tests/placeholders)."""
        data = b"\x00\x00" * int(sample_rate * duration)
        header = (
            b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
            + sample_rate.to_bytes(4, "little") + (sample_rate * 2).to_bytes(4, "little")
            + (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
            + b"data" + len(data).to_bytes(4, "little")
        )
        return header + data
