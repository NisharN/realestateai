"""Pure ingestion scheduling transitions shared by worker and API code."""
from datetime import datetime, timedelta
from typing import Any


def retry_delay_seconds(attempt: int) -> int:
    return min(60 * (2 ** max(attempt - 1, 0)), 900)


def failure_transition(
    failure_count: int,
    error_code: str,
    now: datetime,
    disable_after: int = 5,
) -> dict[str, Any]:
    failures = failure_count + 1
    disabled = failures >= disable_after
    return {
        "failure_count": failures,
        "enabled": not disabled,
        "last_error_code": error_code,
        "next_run_at": None if disabled else (
            now + timedelta(seconds=retry_delay_seconds(failures))
        ).isoformat(),
        "updated_at": now.isoformat(),
    }
