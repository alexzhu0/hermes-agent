from agent.smart_model_routing import choose_cheap_model_route


_BASE_CONFIG = {
    "enabled": True,
    "cheap_model": {
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash",
    },
}


def test_returns_none_when_disabled():
    cfg = {**_BASE_CONFIG, "enabled": False}
    assert choose_cheap_model_route("what time is it in tokyo?", cfg) is None


def test_routes_short_simple_prompt():
    result = choose_cheap_model_route("what time is it in tokyo?", _BASE_CONFIG)
    assert result is not None
    assert result["provider"] == "openrouter"
    assert result["model"] == "google/gemini-2.5-flash"
    assert result["routing_reason"] == "simple_turn"


def test_skips_long_prompt():
    prompt = "please summarize this carefully " * 20
    assert choose_cheap_model_route(prompt, _BASE_CONFIG) is None


def test_skips_code_like_prompt():
    prompt = "debug this traceback: ```python\nraise ValueError('bad')\n```"
    assert choose_cheap_model_route(prompt, _BASE_CONFIG) is None


def test_skips_tool_heavy_prompt_keywords():
    prompt = "implement a patch for this docker error"
    assert choose_cheap_model_route(prompt, _BASE_CONFIG) is None


def test_complex_keywords_extra_extends_builtin():
    """Additional keywords in config should trigger routing skip while
    built-in keywords keep working — useful for non-English workflows."""
    cfg = {**_BASE_CONFIG, "complex_keywords_extra": ["błąd", "napraw"]}
    # Polish trigger word is caught only when extended.
    assert choose_cheap_model_route("co to za błąd w systemie?", cfg) is None
    # Built-in keyword still triggers.
    assert choose_cheap_model_route("debug this for me", cfg) is None
    # Harmless short prompt still routes to cheap model.
    assert choose_cheap_model_route("what time is it?", cfg) is not None


def test_complex_keywords_full_override_replaces_builtin():
    """Setting ``complex_keywords`` replaces the built-in list entirely."""
    cfg = {**_BASE_CONFIG, "complex_keywords": ["zzzonly"]}
    # Built-in 'debug' no longer triggers since the list was overridden.
    assert choose_cheap_model_route("debug this for me", cfg) is not None
    # Only the overridden keyword triggers.
    assert choose_cheap_model_route("what is zzzonly", cfg) is None


def test_complex_keywords_override_beats_extra():
    """When both config keys are present, full override wins for predictability."""
    cfg = {
        **_BASE_CONFIG,
        "complex_keywords": ["solo"],
        "complex_keywords_extra": ["będzie"],
    }
    # 'debug' no longer triggers — overridden list is authoritative.
    assert choose_cheap_model_route("debug this for me", cfg) is not None
    # The extra list is ignored when full override is set.
    assert choose_cheap_model_route("coś będzie tutaj", cfg) is not None
    # Only the override entry triggers.
    assert choose_cheap_model_route("solo trip", cfg) is None


def test_complex_keywords_normalize_case_and_whitespace():
    """Entries are normalized to lowercase and stripped."""
    cfg = {**_BASE_CONFIG, "complex_keywords_extra": ["  BŁĄD  ", "Napraw"]}
    assert choose_cheap_model_route("co to za błąd?", cfg) is None
    assert choose_cheap_model_route("prosze napraw", cfg) is None


def test_complex_keywords_ignore_invalid_types():
    """Malformed values fall back to built-in behavior instead of crashing."""
    # Non-list types are ignored.
    for bad in [{"not": "a list"}, "string", 42, None]:
        cfg = {**_BASE_CONFIG, "complex_keywords_extra": bad}
        # Built-in keyword still works.
        assert choose_cheap_model_route("debug this", cfg) is None
        # Short simple prompt still routes.
        assert choose_cheap_model_route("hi there", cfg) is not None
    # Non-string entries inside a list are skipped silently.
    cfg = {**_BASE_CONFIG, "complex_keywords_extra": ["ok", 1, None, "fine"]}
    assert choose_cheap_model_route("ok fine", cfg) is None


def test_resolve_turn_route_falls_back_to_primary_when_route_runtime_cannot_be_resolved(monkeypatch):
    from agent.smart_model_routing import resolve_turn_route

    monkeypatch.setattr(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("bad route")),
    )
    result = resolve_turn_route(
        "what time is it in tokyo?",
        _BASE_CONFIG,
        {
            "model": "anthropic/claude-sonnet-4",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_mode": "chat_completions",
            "api_key": "sk-primary",
        },
    )
    assert result["model"] == "anthropic/claude-sonnet-4"
    assert result["runtime"]["provider"] == "openrouter"
    assert result["label"] is None
