"""Run the offline conversation evals (evals/cases.yaml) and print a report.

    python -m scripts.run_evals              # all cases, exit 1 on any failure
    python -m scripts.run_evals --only stop  # substring filter on case id

Runs against the in-memory store with the deterministic template path, so it is
safe in CI; set LLM keys to eval the LLM path instead.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings
from app.database import get_lead_repository
from app.modules.conversation.engine import handle_turn
from app.modules.store import reset_memory

CASES = Path(__file__).resolve().parent.parent / "evals" / "cases.yaml"


@dataclass
class CaseResult:
    id: str
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _check(turn: dict[str, Any], result: Any, idx: int, out: list[str]) -> None:
    tag = f"turn {idx} ({turn['say'][:30]!r})"
    if "move" in turn and result.move != turn["move"]:
        out.append(f"{tag}: move {result.move!r} != {turn['move']!r}")
    if "ended" in turn and bool(result.ended) != turn["ended"]:
        out.append(f"{tag}: ended={result.ended}")
    if "handoff" in turn and bool(result.handoff_id) != turn["handoff"]:
        out.append(f"{tag}: handoff_id={result.handoff_id}")
    if "cards_min" in turn and len(result.cards) < turn["cards_min"]:
        out.append(f"{tag}: {len(result.cards)} cards < {turn['cards_min']}")
    if "language" in turn and result.language != turn["language"]:
        out.append(f"{tag}: language {result.language!r}")
    for needle in turn.get("reply_contains", []):
        if needle.lower() not in result.reply.lower():
            out.append(f"{tag}: reply missing {needle!r}: {result.reply!r}")
    for needle in turn.get("reply_excludes", []):
        if needle.lower() in result.reply.lower():
            out.append(f"{tag}: reply contains banned {needle!r}")
    for key, expected in (turn.get("slots") or {}).items():
        actual: Any = result.profile
        for part in key.split("."):
            actual = actual.get(part) if isinstance(actual, dict) else None
        if actual != expected:
            out.append(f"{tag}: slot {key}={actual!r} != {expected!r}")
    if not result.reply.strip():
        out.append(f"{tag}: empty reply")


async def run_case(case: dict[str, Any], workspace_id: str) -> CaseResult:
    res = CaseResult(id=case["id"])
    lead = await get_lead_repository(workspace_id).create(
        {"name": f"eval {case['id']}", "phone": f"+9715{abs(hash(case['id'])) % 10**8:08d}", "source": "website"}
    )
    for i, turn in enumerate(case["turns"], start=1):
        try:
            result = await handle_turn(lead["id"], turn["say"], workspace_id=workspace_id)
        except Exception as exc:  # the engine must never raise
            res.failures.append(f"turn {i}: raised {exc!r}")
            break
        _check(turn, result, i, res.failures)
    return res


async def run_all(only: str | None = None) -> list[CaseResult]:
    ws = get_settings().WORKSPACE_ID
    results: list[CaseResult] = []
    for case in load_cases():
        if only and only not in case["id"]:
            continue
        reset_memory()
        results.append(await run_case(case, ws))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only")
    args = parser.parse_args(argv)
    results = asyncio.run(run_all(args.only))
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.id}")
        for f in r.failures:
            print(f"        - {f}")
    passed = sum(r.ok for r in results)
    print(f"\n{passed}/{len(results)} cases passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
