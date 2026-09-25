"""The only place that talks to an LLM (architecture §10).

``complete_text`` / ``complete_json`` walk an ordered provider chain under one
absolute deadline. Each provider has an in-process circuit breaker (open after
N failures within a window, half-open after a cooldown). When every provider is
skipped or fails, ``LLMUnavailable`` is raised and the caller falls back to
rules or templates — never to an error shown to the buyer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Deque, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

from .providers import (
    Completion,
    Message,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
    ProviderNotConfigured,
    Tier,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    """Raised when no provider produced a valid result within the deadline."""


class CircuitBreaker:
    def __init__(self, failures: int, window_s: float, cooldown_s: float) -> None:
        self.failures = failures
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._events: Deque[float] = deque()
        self._opened_at: float | None = None

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self._opened_at is None:
            return True
        if now - self._opened_at >= self.cooldown_s:
            return True  # half-open: let one call through
        return False

    def record_success(self) -> None:
        self._events.clear()
        self._opened_at = None

    def record_failure(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._events.append(now)
        while self._events and now - self._events[0] > self.window_s:
            self._events.popleft()
        if len(self._events) >= self.failures:
            self._opened_at = now

    @property
    def is_open(self) -> bool:
        return not self.allow()


def build_providers(settings: Settings) -> list[Provider]:
    catalogue: dict[str, Provider] = {
        "groq": OpenAICompatibleProvider(
            "groq",
            "https://api.groq.com/openai/v1",
            settings.GROQ_API_KEY,
            settings.GROQ_MODEL_FAST,
            settings.GROQ_MODEL,
        ),
        "secondary": OpenAICompatibleProvider(
            "secondary",
            settings.LLM_SECONDARY_BASE_URL,
            settings.LLM_SECONDARY_API_KEY,
            settings.LLM_SECONDARY_MODEL_FAST,
            settings.LLM_SECONDARY_MODEL_QUALITY,
        ),
        "ollama": OpenAICompatibleProvider(
            "ollama",
            f"{settings.LLM_OLLAMA_BASE_URL.rstrip('/')}/v1" if settings.LLM_OLLAMA_BASE_URL else "",
            "",
            settings.LLM_OLLAMA_MODEL,
            settings.LLM_OLLAMA_MODEL,
            requires_key=False,
        ),
    }
    return [catalogue[name] for name in settings.llm_providers if name in catalogue]


class LLMGateway:
    def __init__(self, providers: list[Provider] | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.providers = providers if providers is not None else build_providers(self.settings)
        self.breakers = {
            p.name: CircuitBreaker(
                self.settings.LLM_BREAKER_FAILURES,
                self.settings.LLM_BREAKER_WINDOW_S,
                self.settings.LLM_BREAKER_COOLDOWN_S,
            )
            for p in self.providers
        }

    @property
    def available(self) -> bool:
        return any(p.configured() and self.breakers[p.name].allow() for p in self.providers)

    async def complete_text(
        self,
        messages: list[Message],
        *,
        deadline_s: float | None = None,
        tier: Tier = "fast",
        max_tokens: int = 300,
        temperature: float = 0.4,
        json_mode: bool = False,
        purpose: str = "text",
    ) -> Completion:
        budget = self.settings.LLM_RESPOND_TIMEOUT_S if deadline_s is None else deadline_s
        deadline = time.monotonic() + budget
        last_error: str | None = None

        if self.settings.FAULT_LLM_ALL:
            raise LLMUnavailable("fault injection: FAULT_LLM_ALL")

        for provider in self.providers:
            if not provider.configured():
                continue
            breaker = self.breakers[provider.name]
            if not breaker.allow():
                logger.info("llm.skip provider=%s reason=breaker_open purpose=%s", provider.name, purpose)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                last_error = "deadline exhausted"
                break
            try:
                completion = await asyncio.wait_for(
                    provider.complete(
                        messages,
                        tier=tier,
                        timeout_s=remaining,
                        json_mode=json_mode,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=remaining,
                )
            except ProviderNotConfigured:
                continue
            except (ProviderError, asyncio.TimeoutError) as exc:
                breaker.record_failure()
                last_error = str(exc) or "timeout"
                logger.warning("llm.fail provider=%s purpose=%s error=%s", provider.name, purpose, last_error)
                continue
            breaker.record_success()
            logger.info(
                "llm.ok provider=%s model=%s latency_ms=%d purpose=%s",
                completion.provider, completion.model, completion.latency_ms, purpose,
            )
            return completion

        raise LLMUnavailable(last_error or "no provider configured")

    async def complete_json(
        self,
        messages: list[Message],
        schema: Type[T],
        *,
        deadline_s: float | None = None,
        tier: Tier = "fast",
        max_tokens: int = 400,
        purpose: str = "json",
    ) -> T:
        """Validate the model output against ``schema``; one repair attempt."""
        budget = self.settings.LLM_EXTRACT_TIMEOUT_S if deadline_s is None else deadline_s
        deadline = time.monotonic() + budget

        completion = await self.complete_text(
            messages, deadline_s=budget, tier=tier, max_tokens=max_tokens,
            temperature=0.0, json_mode=True, purpose=purpose,
        )
        try:
            return schema.model_validate(_loads(completion.text))
        except (ValueError, ValidationError) as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0.1:
                raise LLMUnavailable("invalid json and no time to repair") from exc
            repair = messages + [
                {"role": "assistant", "content": completion.text},
                {
                    "role": "user",
                    "content": (
                        "That was not valid for the schema. Error: "
                        f"{str(exc)[:400]}. Return ONLY corrected JSON."
                    ),
                },
            ]
            fixed = await self.complete_text(
                repair, deadline_s=remaining, tier=tier, max_tokens=max_tokens,
                temperature=0.0, json_mode=True, purpose=f"{purpose}.repair",
            )
            try:
                return schema.model_validate(_loads(fixed.text))
            except (ValueError, ValidationError) as exc2:
                raise LLMUnavailable("invalid json after repair") from exc2


def _loads(text: str) -> object:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no json object in output")
    return json.loads(text[start : end + 1])


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway


def reset_gateway() -> None:
    global _gateway
    _gateway = None
