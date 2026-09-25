"""Template renderer — the floor of reply quality. Exists for every move."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .moves import Move

_DIR = Path(__file__).parent / "templates"


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


@lru_cache(maxsize=4)
def load(language: str) -> dict[str, Any]:
    path = _DIR / f"{language}.yaml"
    if not path.exists():
        path = _DIR / "en.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _pick(options: list[str], facts: dict[str, Any]) -> str:
    """First option whose placeholders are all present in ``facts``."""
    for option in options:
        needed = _placeholders(option)
        if all(facts.get(k) not in (None, "") for k in needed):
            return option
    return options[-1]


def _placeholders(template: str) -> list[str]:
    out: list[str] = []
    depth_open = False
    current = ""
    for ch in template:
        if ch == "{":
            depth_open, current = True, ""
        elif ch == "}" and depth_open:
            depth_open = False
            out.append(current)
        elif depth_open:
            current += ch
    return out


def render(move: Move | str, language: str, facts: dict[str, Any], *, field: str | None = None, key: str | None = None) -> str:
    """Render the template for ``move`` (or an explicit ``key``) in ``language``."""
    data = load(language if language in ("en", "ar") else "en")
    move_key = key or (move.value if isinstance(move, Move) else str(move))
    entry = data.get(move_key) or data.get("error_fallback") or ["Sorry, could you say that again?"]

    if isinstance(entry, dict):
        # ask_next_field: keyed by field
        options = [entry.get(field or "", "")] if field and entry.get(field) else [next(iter(entry.values()))]
    else:
        options = list(entry)

    text = _pick(options, facts).format_map(_Safe(facts))
    return " ".join(text.split())


def question_for_field(field: str, language: str) -> str:
    data = load(language if language in ("en", "ar") else "en")
    entry = data.get("ask_next_field") or {}
    return entry.get(field) or entry.get("purpose") or ""
