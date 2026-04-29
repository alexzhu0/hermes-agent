"""Tool-runtime time advisory context — #17474 / #17459.

Shared helper surfacing the user's local time, timezone, and configured
contact window to tool handlers whose side effects are time-sensitive
(email send, calendar create, agent mailbox outbox, gateway delivery,
scheduler/autonomy tools).

The returned :class:`ToolRuntimeTimeContext` is designed to be included
verbatim in a tool's return JSON so the agent sees the runtime facts
and decides whether to proceed, defer, or ask for confirmation.

**This is advisory, not enforcement.** Hermes core never silently
suppresses or delays tool calls based on the contact window; see
``TOOL-PRINCIPLES.md`` section 1 and the history in #17459.

Usage::

    from tools.tool_runtime_time_context import build_tool_runtime_time_context

    ctx = build_tool_runtime_time_context()
    result = {"sent": True, "time_context": ctx.to_dict()}

Configuration (all optional, top-level in config.yaml)::

    tool_runtime:
      user_timezone: "America/Los_Angeles"   # IANA TZ, falls back to system local
      contact_window:
        start: "08:00"                       # HH:MM local
        end:   "23:00"                       # HH:MM local
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Default contact window when the user hasn't configured one.  Chosen so
# the default advisory matches typical human business / waking hours
# without being surprising to anyone who hasn't opted into quiet hours.
_DEFAULT_CONTACT_START = time(8, 0)
_DEFAULT_CONTACT_END = time(23, 0)


@dataclass(frozen=True)
class ToolRuntimeTimeContext:
    """Time facts + contact-window advisory a tool can show to the agent.

    * ``now`` — timezone-aware datetime for *this moment* in the user's
      timezone (or system local when none is configured).
    * ``user_timezone`` — IANA name (e.g. ``"America/Los_Angeles"``) or
      ``""`` when the system local timezone was used.
    * ``contact_window`` — ``(start, end)`` strings in ``HH:MM``.  End is
      exclusive; crossing midnight is supported (start > end).
    * ``within_contact_window`` — True when ``now`` falls inside the
      window.
    * ``advisory`` — human-readable text when outside the window;
      empty string when inside.  Agent can forward this to the user.
    """
    now: str
    user_timezone: str
    contact_window: Tuple[str, str]
    within_contact_window: bool
    advisory: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["contact_window"] = list(self.contact_window)
        return d


def _parse_hhmm(value: Any, default: time) -> time:
    """Parse ``HH:MM`` string → ``time``.  Falls back to ``default`` on error."""
    if not isinstance(value, str):
        return default
    parts = value.strip().split(":")
    if len(parts) != 2:
        return default
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return default
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return default
    return time(h, m)


def _resolve_user_tz(configured: Optional[str]) -> Tuple[Optional[Any], str]:
    """Return (tzinfo, iana_name).  Empty iana_name when falling back to system."""
    if configured:
        try:
            from zoneinfo import ZoneInfo  # py >= 3.9
            return ZoneInfo(configured), configured
        except Exception as exc:  # noqa: BLE001 — tz lookup should not fail hard
            logger.debug(
                "tool_runtime_time_context: unknown user_timezone %r (%s); "
                "falling back to system local", configured, exc,
            )
    return None, ""  # caller treats None as "use system local"


def _read_config() -> dict:
    """Best-effort read of hermes config.  Returns {} when unavailable."""
    try:
        from hermes_cli.config import read_raw_config  # type: ignore
    except ImportError:
        return {}
    try:
        cfg = read_raw_config()
    except Exception:  # noqa: BLE001 — never let config errors break a tool call
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _within_window(now_local: time, start: time, end: time) -> bool:
    """Is ``now_local`` inside ``[start, end)``?  Supports wrap-around windows."""
    if start == end:
        # Zero-width window — by convention, nothing is ever inside it.
        return False
    if start < end:
        return start <= now_local < end
    # Window crosses midnight (e.g. 22:00 → 06:00).
    return now_local >= start or now_local < end


def _format_advisory(now_iso: str, user_tz: str, start: str, end: str) -> str:
    """Build the human-readable outside-window advisory string."""
    local = now_iso.split("T", 1)[1][:5] if "T" in now_iso else now_iso
    tz_desc = f"the user's timezone ({user_tz})" if user_tz else "the user's local time"
    return (
        f"It is {local} in {tz_desc}. This is outside their configured "
        f"contact window ({start}–{end}). Consider asking or deferring "
        f"unless urgent."
    )


def build_tool_runtime_time_context(
    *,
    now: Optional[datetime] = None,
    config: Optional[dict] = None,
) -> ToolRuntimeTimeContext:
    """Build a :class:`ToolRuntimeTimeContext` for the current moment.

    Parameters are for testing; callers in production pass neither.

    * ``now`` — override the clock.  Must be timezone-aware.
    * ``config`` — override the config dict.  Same shape as what
      ``hermes_cli.config.read_raw_config()`` would return.
    """
    if config is None:
        config = _read_config()

    tool_rt = config.get("tool_runtime", {}) if isinstance(config, dict) else {}
    if not isinstance(tool_rt, dict):
        tool_rt = {}

    # Timezone resolution
    configured_tz = tool_rt.get("user_timezone")
    if not isinstance(configured_tz, str):
        configured_tz = os.environ.get("HERMES_USER_TIMEZONE", "") or None
    tz_obj, tz_name = _resolve_user_tz(configured_tz)

    # Current moment in the user's timezone
    if now is None:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(tz_obj) if tz_obj else now_utc.astimezone()
    else:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        now_local = now.astimezone(tz_obj) if tz_obj else now

    # Contact window
    window_cfg = tool_rt.get("contact_window", {}) if isinstance(tool_rt, dict) else {}
    if not isinstance(window_cfg, dict):
        window_cfg = {}
    start = _parse_hhmm(window_cfg.get("start"), _DEFAULT_CONTACT_START)
    end = _parse_hhmm(window_cfg.get("end"), _DEFAULT_CONTACT_END)

    within = _within_window(now_local.time(), start, end)
    start_str = f"{start.hour:02d}:{start.minute:02d}"
    end_str = f"{end.hour:02d}:{end.minute:02d}"
    now_iso = now_local.isoformat(timespec="seconds")

    advisory = ""
    if not within:
        advisory = _format_advisory(now_iso, tz_name, start_str, end_str)

    return ToolRuntimeTimeContext(
        now=now_iso,
        user_timezone=tz_name,
        contact_window=(start_str, end_str),
        within_contact_window=within,
        advisory=advisory,
    )
