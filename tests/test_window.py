"""The rolling-window day set: today and the previous ``days_back`` days, UTC.

Pure date logic, no network — verifies :func:`swobml_sync.sync.window_days` in
isolation so the integration tests can trust the day set it produces.
"""

from __future__ import annotations

from datetime import datetime, timezone

from swobml_sync.sync import window_days

NOON = datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc)


def test_default_lookback_is_today_and_previous_two_days() -> None:
    assert window_days(NOON, 2) == ["20260710", "20260709", "20260708"]


def test_zero_days_back_is_today_only() -> None:
    assert window_days(NOON, 0) == ["20260710"]


def test_window_crosses_month_boundary() -> None:
    assert window_days(datetime(2026, 3, 1, tzinfo=timezone.utc), 2) == [
        "20260301",
        "20260228",
        "20260227",
    ]


def test_window_is_computed_in_utc() -> None:
    # Just before UTC midnight the day is still the 10th, not the 11th, even
    # though it is already the 11th in a positive-offset local zone.
    late = datetime(2026, 7, 10, 23, 59, tzinfo=timezone.utc)
    assert window_days(late, 0) == ["20260710"]
