"""Helpers for optional cheap-vs-strong model routing."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from utils import is_truthy_value

_COMPLEX_KEYWORDS = {
    "debug",
    "debugging",
    "implement",
    "implementation",
    "refactor",
    "patch",
    "traceback",
    "stacktrace",
    "exception",
    "error",
    "analyze",
    "analysis",
    "investigate",
    "architecture",
    "design",
    "compare",
    "benchmark",
    "optimize",
    "optimise",
    "review",
    "terminal",
    "shell",
    "tool",
    "tools",
    "pytest",
    "test",
    "tests",
    "plan",
    "planning",
    "delegate",
    "subagent",
    "cron",
    "docker",
    "kubernetes",
}

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return is_truthy_value(value, default=default)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_keyword_list(value: Any) -> set[str]:
    """Coerce a config value into a lowercase-stripped set of keywords.

    Accepts a list/tuple of strings; ignores other types and non-string
    entries so malformed config degrades to the built-in behavior rather
    than crashing the router.
    """
    if not isinstance(value, (list, tuple)):
        return set()
    out: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        word = item.strip().lower()
        if word:
            out.add(word)
    return out


def _resolve_complex_keywords(cfg: Dict[str, Any]) -> set[str]:
    """Return the effective complex-keyword set for this routing config.

    - ``complex_keywords`` (list[str]) fully replaces the built-in list.
    - ``complex_keywords_extra`` (list[str]) extends the built-in list.
    - When both are set, ``complex_keywords`` wins (full override) and
      ``complex_keywords_extra`` is ignored — preserving the predictable
      behavior a self-hoster who sets an explicit list would expect.
    - Malformed values (non-list, non-string entries) are silently
      ignored so a broken config falls back to the built-in list.
    """
    override = _normalize_keyword_list(cfg.get("complex_keywords"))
    if override:
        return override
    extra = _normalize_keyword_list(cfg.get("complex_keywords_extra"))
    return _COMPLEX_KEYWORDS | extra


def choose_cheap_model_route(user_message: str, routing_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the configured cheap-model route when a message looks simple.

    Conservative by design: if the message has signs of code/tool/debugging/
    long-form work, keep the primary model.

    Routing skips the cheap model when the message contains any keyword in
    the effective complex-keyword set. The set defaults to a built-in
    English list and can be extended or fully overridden via
    ``complex_keywords_extra`` / ``complex_keywords`` in ``routing_config``
    — useful for non-English workflows where the built-in list misses
    domain-specific triggers.
    """
    cfg = routing_config or {}
    if not _coerce_bool(cfg.get("enabled"), False):
        return None

    cheap_model = cfg.get("cheap_model") or {}
    if not isinstance(cheap_model, dict):
        return None
    provider = str(cheap_model.get("provider") or "").strip().lower()
    model = str(cheap_model.get("model") or "").strip()
    if not provider or not model:
        return None

    text = (user_message or "").strip()
    if not text:
        return None

    max_chars = _coerce_int(cfg.get("max_simple_chars"), 160)
    max_words = _coerce_int(cfg.get("max_simple_words"), 28)

    if len(text) > max_chars:
        return None
    if len(text.split()) > max_words:
        return None
    if text.count("\n") > 1:
        return None
    if "```" in text or "`" in text:
        return None
    if _URL_RE.search(text):
        return None

    lowered = text.lower()
    words = {token.strip(".,:;!?()[]{}\"'`") for token in lowered.split()}
    if words & _resolve_complex_keywords(cfg):
        return None

    route = dict(cheap_model)
    route["provider"] = provider
    route["model"] = model
    route["routing_reason"] = "simple_turn"
    return route


def resolve_turn_route(user_message: str, routing_config: Optional[Dict[str, Any]], primary: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the effective model/runtime for one turn.

    Returns a dict with model/runtime/signature/label fields.
    """
    route = choose_cheap_model_route(user_message, routing_config)
    if not route:
        return {
            "model": primary.get("model"),
            "runtime": {
                "api_key": primary.get("api_key"),
                "base_url": primary.get("base_url"),
                "provider": primary.get("provider"),
                "api_mode": primary.get("api_mode"),
                "command": primary.get("command"),
                "args": list(primary.get("args") or []),
                "credential_pool": primary.get("credential_pool"),
            },
            "label": None,
            "signature": (
                primary.get("model"),
                primary.get("provider"),
                primary.get("base_url"),
                primary.get("api_mode"),
                primary.get("command"),
                tuple(primary.get("args") or ()),
            ),
        }

    from hermes_cli.runtime_provider import resolve_runtime_provider

    explicit_api_key = None
    api_key_env = str(route.get("api_key_env") or "").strip()
    if api_key_env:
        explicit_api_key = os.getenv(api_key_env) or None

    try:
        runtime = resolve_runtime_provider(
            requested=route.get("provider"),
            explicit_api_key=explicit_api_key,
            explicit_base_url=route.get("base_url"),
        )
    except Exception:
        return {
            "model": primary.get("model"),
            "runtime": {
                "api_key": primary.get("api_key"),
                "base_url": primary.get("base_url"),
                "provider": primary.get("provider"),
                "api_mode": primary.get("api_mode"),
                "command": primary.get("command"),
                "args": list(primary.get("args") or []),
                "credential_pool": primary.get("credential_pool"),
            },
            "label": None,
            "signature": (
                primary.get("model"),
                primary.get("provider"),
                primary.get("base_url"),
                primary.get("api_mode"),
                primary.get("command"),
                tuple(primary.get("args") or ()),
            ),
        }

    return {
        "model": route.get("model"),
        "runtime": {
            "api_key": runtime.get("api_key"),
            "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"),
            "api_mode": runtime.get("api_mode"),
            "command": runtime.get("command"),
            "args": list(runtime.get("args") or []),
            "credential_pool": runtime.get("credential_pool"),
        },
        "label": f"smart route → {route.get('model')} ({runtime.get('provider')})",
        "signature": (
            route.get("model"),
            runtime.get("provider"),
            runtime.get("base_url"),
            runtime.get("api_mode"),
            runtime.get("command"),
            tuple(runtime.get("args") or ()),
        ),
    }
