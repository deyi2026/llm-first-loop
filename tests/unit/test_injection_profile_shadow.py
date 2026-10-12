"""P1-C: runtime Injection Profile recommendation/emission is retired."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec


def _registry(*, tier: str) -> ProviderRegistry:
    return ProviderRegistry(
        providers={
            "p": ProviderSpec(
                id="p",
                base_url="http://example.invalid/v1",
                api_key_env="",
                models={"m": ModelSpec(capability_tier=tier, context=131072)},
                default_model="m",
            )
        }
    )


def test_runtime_injection_profile_module_is_retired() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/core/injection_profile.py").exists()
    assert importlib.util.find_spec("llm_loop.core.injection_profile") is None


def test_historical_profile_event_schema_is_read_compatibility_only() -> None:
    from llm_loop.event_log.model import EVENT_INJECTION_PROFILE_SHADOW, REGISTRY

    assert EVENT_INJECTION_PROFILE_SHADOW == "injection.profile.shadow"
    assert REGISTRY.spec(EVENT_INJECTION_PROFILE_SHADOW) is not None

    # No current provider-attempt path may emit or import the retired recommendation.
    from llm_loop.core.loop import engine
    from llm_loop.core.loop.engine_services import fallback, recovery_controller

    for module in (engine, fallback, recovery_controller):
        src = inspect.getsource(module)
        assert "shadow_profile_event_payload" not in src
        assert "EVENT_INJECTION_PROFILE_SHADOW" not in src
        assert "injection.profile.shadow 事件写入失败" not in src


def test_capability_tier_does_not_change_provider_payload_or_emit_profile(tmp_path) -> None:
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

    def _run(name: str, registry: ProviderRegistry) -> tuple[str, list[str]]:
        fake = _CaptureLLM()
        pool = ModelClientPool(registry=registry, default_client=fake)  # type: ignore[arg-type]
        settings = Settings(
            llm_api_key="",
            llm_base_url="http://example.invalid/v1",
            llm_model="m",
            data_dir=str(tmp_path / name / "data"),
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
        result = engine.run_single("任务")
        normalized_payloads = [
            (
                [
                    {k: v for k, v in message.items() if k != "_message_time_ts"}
                    for message in messages
                ],
                tools,
            )
            for messages, tools in fake.payloads
        ]
        payload = json.dumps(normalized_payloads, ensure_ascii=False, sort_keys=True)
        event_types = [event.type for event in events.read(result.session_id)]
        return payload, event_types

    weak_payload, weak_events = _run("weak", _registry(tier="weak"))
    strong_payload, strong_events = _run("strong", _registry(tier="strong"))
    assert weak_payload == strong_payload
    assert "injection.profile.shadow" not in weak_events
    assert "injection.profile.shadow" not in strong_events
