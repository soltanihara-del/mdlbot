from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.quota import quota_window


def test_quota_windows_have_exact_utc_boundaries() -> None:
    now = datetime(2026, 7, 22, 14, 37, 41, tzinfo=UTC)
    assert quota_window("hourly", now).start == datetime(2026, 7, 22, 14, tzinfo=UTC)
    assert quota_window("daily", now).start == datetime(2026, 7, 22, tzinfo=UTC)
    weekly = quota_window("weekly", now)
    assert weekly.start == datetime(2026, 7, 20, tzinfo=UTC)
    assert weekly.end == datetime(2026, 7, 27, tzinfo=UTC)


def test_unknown_quota_window_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported quota window"):
        quota_window("monthly", datetime.now(UTC))
