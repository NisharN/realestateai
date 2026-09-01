from datetime import datetime, timedelta, timezone

from app.services.ingestion_jobs import failure_transition, retry_delay_seconds


def test_retry_backoff_is_bounded_exponential():
    assert [retry_delay_seconds(attempt) for attempt in range(1, 7)] == [60, 120, 240, 480, 900, 900]


def test_repeated_failure_disables_schedule_and_preserves_diagnostics():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)

    transition = failure_transition(
        failure_count=4,
        error_code="provider_timeout",
        now=now,
        disable_after=5,
    )

    assert transition == {
        "failure_count": 5,
        "enabled": False,
        "last_error_code": "provider_timeout",
        "next_run_at": None,
        "updated_at": now.isoformat(),
    }


def test_failure_before_threshold_schedules_retry():
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)
    transition = failure_transition(1, "bad_feed", now, disable_after=5)

    assert transition["enabled"] is True
    assert transition["failure_count"] == 2
    assert transition["next_run_at"] == (now + timedelta(seconds=120)).isoformat()
