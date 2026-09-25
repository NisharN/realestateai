"""OpenAI-compatible chat-completions provider (Groq, OpenRouter, Together, Ollama…)."""
from __future__ import annotations

import time

import httpx

from .base import Completion, Message, ProviderError, ProviderNotConfigured, Tier


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model_fast: str,
        model_quality: str,
        *,
        requires_key: bool = True,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_fast = model_fast
        self.model_quality = model_quality or model_fast
        self.requires_key = requires_key

    def configured(self) -> bool:
        if not self.base_url or not self.model_fast:
            return False
        return bool(self.api_key) or not self.requires_key

    def _model(self, tier: Tier) -> str:
        return self.model_quality if tier == "quality" else self.model_fast

    async def complete(
        self,
        messages: list[Message],
        *,
        tier: Tier,
        timeout_s: float,
        json_mode: bool,
        max_tokens: int,
        temperature: float,
    ) -> Completion:
        if not self.configured():
            raise ProviderNotConfigured(self.name)
        model = self._model(tier)
        body: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name}: timeout after {timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: transport error {exc}") from exc

        if response.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {response.status_code}")
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name}: malformed response") from exc

        usage_raw = payload.get("usage") or {}
        usage = {k: int(v) for k, v in usage_raw.items() if isinstance(v, (int, float))}
        return Completion(
            text=text,
            provider=self.name,
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=usage,
        )
