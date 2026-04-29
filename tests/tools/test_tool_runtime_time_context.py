"""Tests for tools.tool_runtime_time_context — #17474."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tools.tool_runtime_time_context import (
    ToolRuntimeTimeContext,
    _parse_hhmm,
    _within_window,
    build_tool_runtime_time_context,
)
from datetime import time as dtime


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_parse_hhmm_valid():
    assert _parse_hhmm("08:30", dtime(0, 0)) == dtime(8, 30)
    assert _parse_hhmm("00:00", dtime(0, 0)) == dtime(0, 0)
    assert _parse_hhmm("23:59", dtime(0, 0)) == dtime(23, 59)


def test_parse_hhmm_invalid_falls_back():
    default = dtime(8, 0)
    assert _parse_hhmm(None, default) == default
    assert _parse_hhmm("", default) == default
    assert _parse_hhmm("24:00", default) == default
    assert _parse_hhmm("abc", default) == default
    assert _parse_hhmm("8:30:00", default) == default
    assert _parse_hhmm(8.5, default) == default


def test_within_window_normal_hours():
    assert _within_window(dtime(10, 0), dtime(8, 0), dtime(23, 0)) is True
    assert _within_window(dtime(7, 59), dtime(8, 0), dtime(23, 0)) is False
    assert _within_window(dtime(23, 0), dtime(8, 0), dtime(23, 0)) is False
    assert _within_window(dtime(8, 0), dtime(8, 0), dtime(23, 0)) is True


def test_within_window_crosses_midnight():
    # Night-owl window 22:00 → 06:00
    assert _within_window(dtime(22, 0), dtime(22, 0), dtime(6, 0)) is True
    assert _within_window(dtime(2, 0), dtime(22, 0), dtime(6, 0)) is True
    assert _within_window(dtime(6, 0), dtime(22, 0), dtime(6, 0)) is False
    assert _within_window(dtime(12, 0), dtime(22, 0), dtime(6, 0)) is False


def test_within_window_zero_width_is_empty():
    """A window where start == end is treated as empty, not full-day."""
    assert _within_window(dtime(12, 0), dtime(8, 0), dtime(8, 0)) is False
    assert _within_window(dtime(8, 0), dtime(8, 0), dtime(8, 0)) is False


# ── build_tool_runtime_time_context integration ──────────────────────────────


def test_default_config_inside_window():
    """Default window 08:00–23:00; 10:00 local is inside."""
    now = datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(now=now, config={})
    assert ctx.within_contact_window is True
    assert ctx.advisory == ""
    assert ctx.contact_window == ("08:00", "23:00")


def test_default_config_outside_window():
    """Default window 08:00–23:00; 02:00 UTC (= 02:00 in default TZ when
    no tz configured and test env's TZ is UTC) is outside."""
    now = datetime(2026, 4, 29, 2, 14, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={"tool_runtime": {"user_timezone": "UTC"}},
    )
    assert ctx.within_contact_window is False
    assert "outside" in ctx.advisory
    assert "02:14" in ctx.advisory


def test_configured_user_timezone_shifts_clock():
    """User in America/Los_Angeles sees LA time, not UTC."""
    now_utc = datetime(2026, 4, 29, 15, 0, tzinfo=timezone.utc)  # 08:00 PDT
    ctx = build_tool_runtime_time_context(
        now=now_utc,
        config={"tool_runtime": {"user_timezone": "America/Los_Angeles"}},
    )
    assert ctx.user_timezone == "America/Los_Angeles"
    # 08:00 PDT is the default-window start, so inside.
    assert ctx.within_contact_window is True


def test_custom_contact_window():
    """User overrides contact window to 09:00–17:00 business hours."""
    now = datetime(2026, 4, 29, 8, 30, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={
            "tool_runtime": {
                "user_timezone": "UTC",
                "contact_window": {"start": "09:00", "end": "17:00"},
            }
        },
    )
    assert ctx.within_contact_window is False
    assert ctx.contact_window == ("09:00", "17:00")
    assert "09:00–17:00" in ctx.advisory


def test_wrap_around_window_at_night():
    """Night-owl window 22:00–06:00; 03:00 is inside."""
    now = datetime(2026, 4, 29, 3, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={
            "tool_runtime": {
                "user_timezone": "UTC",
                "contact_window": {"start": "22:00", "end": "06:00"},
            }
        },
    )
    assert ctx.within_contact_window is True
    assert ctx.advisory == ""


def test_unknown_timezone_falls_back_to_system():
    """A malformed TZ name shouldn't crash — just use system local."""
    now = datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={"tool_runtime": {"user_timezone": "Not/A_Real_Zone"}},
    )
    # user_timezone empty when we fell back
    assert ctx.user_timezone == ""


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        build_tool_runtime_time_context(now=datetime(2026, 4, 29, 10, 0))


def test_to_dict_is_json_serializable_shape():
    """contact_window must be a list (not tuple) so json.dumps works."""
    import json

    now = datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={"tool_runtime": {"user_timezone": "UTC"}},
    )
    d = ctx.to_dict()
    assert isinstance(d["contact_window"], list)
    # Round-trip through json without raising
    assert json.loads(json.dumps(d))["contact_window"] == ["08:00", "23:00"]


def test_advisory_absent_when_inside_window():
    now = datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={"tool_runtime": {"user_timezone": "UTC"}},
    )
    assert ctx.advisory == ""
    assert ctx.within_contact_window is True


def test_malformed_window_entries_fall_back():
    """Garbage in tool_runtime.contact_window doesn't break tool calls."""
    now = datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc)
    ctx = build_tool_runtime_time_context(
        now=now,
        config={
            "tool_runtime": {
                "user_timezone": "UTC",
                "contact_window": {"start": "not a time", "end": 42},
            }
        },
    )
    # Falls back to defaults 08:00–23:00
    assert ctx.contact_window == ("08:00", "23:00")
