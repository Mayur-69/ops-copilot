from __future__ import annotations

from pathlib import Path

import pytest

from src.usage import UsageLimitError, UsageTracker


def test_daily_limit_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "usage.db"
    tracker = UsageTracker(path)
    assert tracker.daily_count("2026-11-01") == 0
    assert tracker.check_and_increment(2, day="2026-11-01") == 1
    assert tracker.check_and_increment(2, day="2026-11-01") == 2
    with pytest.raises(UsageLimitError):
        tracker.check_and_increment(2, day="2026-11-01")
    assert tracker.daily_count("2026-11-01") == 2

    restarted = UsageTracker(path)
    assert restarted.daily_count("2026-11-01") == 2
    assert restarted.check_and_increment(2, day="2026-11-02") == 1
    assert restarted.daily_count("2026-11-01") == 2
    assert restarted.daily_count("2026-11-02") == 1


def test_invalid_cap(tmp_path: Path) -> None:
    tracker = UsageTracker(tmp_path / "usage.db")
    with pytest.raises(ValueError):
        tracker.check_and_increment(0)
