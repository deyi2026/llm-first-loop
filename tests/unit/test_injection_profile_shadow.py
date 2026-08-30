from __future__ import annotations

from llm_loop.core.injection_profile import (
    InjectionProfile,
    recommend_injection_profile,
)
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec


def _registry(*, tier: str, reasoning: bool = False) -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="http://example.invalid/v1",
                api_key_env="",
                models={
                    "m": ModelSpec(
                        capability_tier=tier,
                        reasoning=reasoning,
                        context=131072,
                    )
                },
                default_model="m",
            )
        }
    )


def test_weak_capability_recommends_minimal() -> None:
    rec = recommend_injection_profile("p/m", _registry(tier="weak"))
    assert rec.profile is InjectionProfile.MINIMAL
    assert rec.capability_tier == "weak"
    assert rec.mode == "shadow"
    assert rec.applied is False
    assert rec.source == "provider_registry"


def test_unknown_capability_is_conservatively_minimal() -> None:
    rec = recommend_injection_profile("p/m", _registry(tier="unknown"))
    assert rec.profile is InjectionProfile.MINIMAL
    assert rec.capability_tier == "unknown"
    assert rec.reason == "unknown_capability_conservative"


def test_strong_non_reasoning_recommends_standard() -> None:
    rec = recommend_injection_profile("p/m", _registry(tier="strong", reasoning=False))
    assert rec.profile is InjectionProfile.STANDARD
    assert rec.reason == "strong_without_reasoning_capability"


def test_strong_reasoning_recommends_full() -> None:
    rec = recommend_injection_profile("p/m", _registry(tier="strong", reasoning=True))
    assert rec.profile is InjectionProfile.FULL
    assert rec.reason == "strong_reasoning_capability"


def test_unresolved_or_missing_registry_fails_safe_to_minimal() -> None:
    missing = recommend_injection_profile("p/m", None)
    unresolved = recommend_injection_profile("p/other", _registry(tier="strong", reasoning=True))
    assert missing.profile is InjectionProfile.MINIMAL
    assert missing.source == "registry_unavailable"
    assert missing.capability_tier == "unknown"
    assert unresolved.profile is InjectionProfile.MINIMAL
    assert unresolved.source == "model_unresolved"
    assert unresolved.capability_tier == "unknown"


def test_model_name_never_overrides_provider_capability() -> None:
    strong = ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="http://example.invalid/v1",
                api_key_env="",
                models={"tiny-weak-looking-model": ModelSpec(capability_tier="strong", reasoning=True)},
            )
        }
    )
    unknown = ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="http://example.invalid/v1",
                api_key_env="",
                models={"ultra-pro-strong-model": ModelSpec(capability_tier="unknown", reasoning=True)},
            )
        }
    )
    assert recommend_injection_profile("p/tiny-weak-looking-model", strong).profile is InjectionProfile.FULL
    assert recommend_injection_profile("p/ultra-pro-strong-model", unknown).profile is InjectionProfile.MINIMAL


def test_event_payload_is_explicitly_shadow_only() -> None:
    payload = recommend_injection_profile("p/m", _registry(tier="weak")).event_payload()
    assert payload == {
        "injection_profile_mode": "shadow",
        "recommended_injection_profile": "minimal",
        "injection_profile_applied": False,
        "model_capability_tier": "weak",
        "injection_profile_source": "provider_registry",
        "injection_profile_reason": "weak_capability",
    }


def test_request_meta_records_routed_registry_shadow_profile(tmp_path) -> None:
    """R8 attribution follows the registry snapshot used by actual routing."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.tools.registry import ToolRegistry

    class _FakeLLM:
        model = "m"
        max_tokens = 128
        reasoning_effort = "high"
        thinking_supported = True
        wire_protocol = "openai"

        def chat_stream(self, messages, tools, **kwargs):
            del messages, tools, kwargs

            def _gen():
                yield from ()
                return LLMResponse(content="完成", tool_calls=[], provider="fake")

            return _gen()

    registry = _registry(tier="strong", reasoning=True)
    fake = _FakeLLM()
    pool = ModelClientPool(registry=registry, default_client=fake)  # type: ignore[arg-type]
    settings = Settings(
        llm_api_key="",
        llm_base_url="http://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    event_store = EventStore(tmp_path / "events")
    session_store = SessionStore(tmp_path / "sessions", event_store=event_store)
    engine = LoopEngine(
        llm_client=fake,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=session_store,
        settings=settings,
        llm_pool=pool,
        event_store=event_store,
    )

    result = engine.run_single("任务")
    profiles = [
        event for event in event_store.read(result.session_id)
        if event.type == "injection.profile.shadow"
    ]
    assert len(profiles) == 1
    payload = profiles[0].payload
    assert payload["model"] == "p/m"
    assert payload["mode"] == "shadow"
    assert payload["recommended_injection_profile"] == "full"
    assert payload["model_capability_tier"] == "strong"
    assert payload["source"] == "provider_registry"
    assert payload["reason"] == "strong_reasoning_capability"
    assert payload["applied"] is False
    assert payload["attempt_kind"] == "primary"
    assert payload["attempt_index"] == 0


def test_shadow_event_registry_documents_r8_fields() -> None:
    from llm_loop.event_log.model import EVENT_INJECTION_PROFILE_SHADOW, REGISTRY

    spec = REGISTRY.spec(EVENT_INJECTION_PROFILE_SHADOW)
    assert spec is not None
    assert {
        "round", "attempt_kind", "attempt_index", "model", "mode",
        "recommended_injection_profile", "applied", "model_capability_tier",
        "source", "reason",
    } <= set(spec.fields)


def test_shadow_profile_change_is_provider_payload_byte_identical(tmp_path) -> None:
    """Changing only capability metadata may change telemetry, never provider input."""
    import json

    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.tools.registry import ToolRegistry

    class _CaptureLLM:
        model = "m"
        max_tokens = 128
        reasoning_effort = "high"
        thinking_supported = True
        wire_protocol = "openai"

        def __init__(self) -> None:
            self.payloads: list[tuple[list[dict], list[dict]]] = []

        def chat_stream(self, messages, tools, **kwargs):
            del kwargs
            self.payloads.append((messages, tools))

            def _gen():
                yield from ()
                return LLMResponse(content="完成", tool_calls=[], provider="fake")

            return _gen()

    def _run(name: str, registry: ProviderRegistry) -> tuple[str, dict]:
        fake = _CaptureLLM()
        pool = ModelClientPool(registry=registry, default_client=fake)  # type: ignore[arg-type]
        settings = Settings(
            llm_api_key="",
            llm_base_url="http://example.invalid/v1",
            llm_model="m",
            data_dir=str(tmp_path / "shared-data"),
            extract_enabled=False,
            summary_mode="off",
        )
        events = EventStore(tmp_path / name / "events")
        sessions = SessionStore(tmp_path / name / "sessions", event_store=events)
        engine = LoopEngine(
            llm_client=fake,  # type: ignore[arg-type]
            registry=ToolRegistry(),
            memory=None,  # type: ignore[arg-type]
            session=sessions,
            settings=settings,
            llm_pool=pool,
            event_store=events,
        )
        result = engine.run_single("保持原样回答这个任务")
        assert len(fake.payloads) == 1
        wire = json.dumps(fake.payloads[0], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        meta = next(
            event.payload for event in events.read(result.session_id)
            if event.type == "injection.profile.shadow"
        )
        return wire, meta

    weak_wire, weak_meta = _run("weak", _registry(tier="weak", reasoning=False))
    full_wire, full_meta = _run("full", _registry(tier="strong", reasoning=True))

    assert weak_meta["recommended_injection_profile"] == "minimal"
    assert full_meta["recommended_injection_profile"] == "full"
    assert weak_meta["applied"] is False
    assert full_meta["applied"] is False
    assert weak_wire == full_wire


def test_fallback_attempts_get_exact_shadow_attribution(tmp_path) -> None:
    """Primary and every real fallback provider attempt get their own profile event."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.llm.errors import LLMHTTPError, LLMTimeoutError
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from llm_loop.tools.registry import ToolRegistry

    class _Client:
        timeout_s = 30.0
        max_tokens = 128
        reasoning_effort = "high"
        thinking_mode = True
        thinking_supported = True
        wire_protocol = "openai"

        def __init__(self, model: str, result) -> None:
            self.model = model
            self.result = result
            self.calls = 0

        def chat(self, messages, tools, **kwargs):
            del messages, tools, kwargs
            self.calls += 1
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    registry = ProviderRegistry(
        providers={
            "primary": ProviderSpec(
                id="primary",
                base_url="http://primary.invalid/v1",
                api_key_env="",
                models={"m": ModelSpec(capability_tier="weak")},
                default_model="m",
            ),
            "fb1": ProviderSpec(
                id="fb1",
                base_url="http://fb1.invalid/v1",
                api_key_env="",
                models={"m1": ModelSpec(capability_tier="strong", reasoning=False)},
                default_model="m1",
            ),
            "fb2": ProviderSpec(
                id="fb2",
                base_url="http://fb2.invalid/v1",
                api_key_env="",
                models={"m2": ModelSpec(capability_tier="strong", reasoning=True)},
                default_model="m2",
            ),
        }
    )
    primary = _Client(
        "m",
        LLMHTTPError("rate limited", status_code=429, body="", provider="primary"),
    )
    fb1 = _Client("m1", LLMTimeoutError("fallback one timeout"))
    fb2 = _Client("m2", LLMResponse(content="fallback ok", tool_calls=[], provider="fb2"))
    pool = ModelClientPool(
        registry=registry,
        default_client=primary,  # type: ignore[arg-type]
        model_fallbacks_raw="fb1/m1,fb2/m2",
    )
    pool._provider_cache["fb1"] = fb1  # type: ignore[assignment]  # noqa: SLF001
    pool._provider_cache["fb2"] = fb2  # type: ignore[assignment]  # noqa: SLF001

    settings = Settings(
        llm_api_key="",
        llm_base_url="http://primary.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    engine = LoopEngine(
        llm_client=primary,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        llm_pool=pool,
        event_store=events,
    )

    result = engine.run_single("任务")
    assert result.final_answer.startswith("fallback ok")
    assert result.model_used == "fb2/m2"
    assert primary.calls == 1 and fb1.calls == 1 and fb2.calls == 1

    profiles = [
        event.payload for event in events.read(result.session_id)
        if event.type == "injection.profile.shadow"
    ]
    assert [(p["attempt_kind"], p["attempt_index"], p["model"]) for p in profiles] == [
        ("primary", 0, "primary/m"),
        ("fallback", 1, "fb1/m1"),
        ("fallback", 2, "fb2/m2"),
    ]
    assert [p["recommended_injection_profile"] for p in profiles] == [
        "minimal", "standard", "full"
    ]
    assert all(p["mode"] == "shadow" and p["applied"] is False for p in profiles)


def test_err1210_retry_gets_shadow_attempt_event(tmp_path, monkeypatch) -> None:
    """A 1210 blind retry is a second real provider attempt, not hidden telemetry."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.llm.errors import LLMHTTPError
    from llm_loop.llm.pool import ModelClientPool
    from llm_loop.tools.registry import ToolRegistry

    class _RetryClient:
        model = "m"
        timeout_s = 30.0
        max_tokens = 128
        reasoning_effort = "high"
        thinking_mode = True
        thinking_supported = True
        wire_protocol = "openai"

        def __init__(self) -> None:
            self.calls = 0

        def chat(self, messages, tools, **kwargs):
            del messages, tools, kwargs
            self.calls += 1
            if self.calls == 1:
                raise LLMHTTPError(
                    "400 Invalid parameter",
                    status_code=400,
                    body='{"error":{"code":"1210","message":"Invalid parameter"}}',
                    provider="p",
                )
            return LLMResponse(content="retry ok", tool_calls=[], provider="p")

    monkeypatch.setenv("ERR1210_RECOVERY", "1")
    monkeypatch.setenv("ERR1210_BLIND_RETRY", "1")
    registry = _registry(tier="weak")
    client = _RetryClient()
    pool = ModelClientPool(registry=registry, default_client=client)  # type: ignore[arg-type]
    settings = Settings(
        llm_api_key="",
        llm_base_url="http://example.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    events = EventStore(tmp_path / "events")
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    engine = LoopEngine(
        llm_client=client,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        memory=None,  # type: ignore[arg-type]
        session=sessions,
        settings=settings,
        llm_pool=pool,
        event_store=events,
    )

    result = engine.run_single("任务")
    assert result.final_answer.startswith("retry ok")
    assert client.calls == 2
    profiles = [
        event.payload for event in events.read(result.session_id)
        if event.type == "injection.profile.shadow"
    ]
    assert [(p["attempt_kind"], p["attempt_index"], p["model"]) for p in profiles] == [
        ("primary", 0, "p/m"),
        ("err1210_retry", 1, "p/m"),
    ]
    assert all(p["recommended_injection_profile"] == "minimal" for p in profiles)
    assert all(p["applied"] is False for p in profiles)
