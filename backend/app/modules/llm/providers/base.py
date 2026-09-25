"""Provider protocol for the LLM gateway.

Every provider speaks the OpenAI chat-completions shape and is given an
absolute per-call timeout by the gateway. Providers never retry themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Message = dict[str, str]
Tier = Literal["fast", "quality"]


class ProviderError(Exception):
    """Any failure the gateway should count towards the circuit breaker."""


class ProviderNotConfigured(ProviderError):
    """Provider lacks credentials/base URL and must be skipped silently."""


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def configured(self) -> bool: ...

    async def complete(
        self,
        messages: list[Message],
        *,
        tier: Tier,
        timeout_s: float,
        json_mode: bool,
        max_tokens: int,
        temperature: float,
    ) -> Completion: ...
