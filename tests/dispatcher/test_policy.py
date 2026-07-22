from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.dispatcher.service import choose_lane


def test_vip_is_preferred_within_fairness_budget() -> None:
    now = datetime.now(UTC)
    assert choose_lane(
        oldest_normal=now - timedelta(seconds=30),
        now=now,
        consecutive_vip=3,
        max_normal_wait_seconds=300,
        max_consecutive_vip=4,
    ) == "vip"


def test_normal_lane_is_forced_by_ratio_or_wait_bound() -> None:
    now = datetime.now(UTC)
    common = {
        "now": now,
        "max_normal_wait_seconds": 300,
        "max_consecutive_vip": 4,
    }
    assert choose_lane(
        oldest_normal=now - timedelta(seconds=30), consecutive_vip=4, **common
    ) == "normal"
    assert choose_lane(
        oldest_normal=now - timedelta(seconds=301), consecutive_vip=0, **common
    ) == "normal"
