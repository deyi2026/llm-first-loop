"""ModelClientPool / route / fallback 的 per-model 真实选路回归。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from llm_loop.llm.client import LLMResponse
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec


def _default_client():
    return SimpleNamespace(
        timeout_s=60.0,
        max_tokens=4096,
        wire_protocol="openai",
        thinking_mode=True,
        reasoning_effort="high",
        thinking_supported=True,
        model="model-a",
        close=lambda: None,
    )


def test_pool_caches_clients_per_provider_model(monkeypatch):
    """同 provider 的两个模型可有不同 endpoint/capability，不能复用首个 client。"""
    registry = ProviderRegistry(
        providers={
            "shared": ProviderSpec(
                id="shared",
                base_url="http://configured/v1",
                api_key_env="X",
                models={
                    "model-a": ModelSpec(
                        thinking=True,
                        reasoning_capable=True,
                        reasoning_control="thinking_type",
                        reasoning_split=True,
                    ),
                    "model-b": ModelSpec(
                        thinking=False,
                        reasoning_capable=True,
                        reasoning_control="unknown",
                    ),
                },
            )
        }
    )
    monkeypatch.setattr(
        ProviderRegistry,
        "client_params",
        lambda self, pid, mid: {
            "api_key": "k",
            "base_url": f"http://{mid}.local/v1",
            "model": mid,
            "timeout_s": None,
            "max_tokens": None,
            "wire_protocol": "openai",
            "reasoning_split": mid == "model-a",
        },
    )
    made: list[SimpleNamespace] = []

    def build_client(**kwargs):
        obj = SimpleNamespace(**kwargs, close=lambda: None)
        made.append(obj)
        return obj

    with mock.patch("llm_loop.llm.pool.LLMClient", side_effect=build_client):
        pool = ModelClientPool(registry=registry, default_client=_default_client())  # type: ignore[arg-type]
        a = pool.get_client("shared/model-a")
        b = pool.get_client("shared/model-b")

    assert a is not b
    assert a.base_url == "http://model-a.local/v1"
    assert b.base_url == "http://model-b.local/v1"
    assert a.thinking_supported is True
    assert b.thinking_supported is False
    assert a.reasoning_capable is True
    assert a.reasoning_control == "thinking_type"
    assert b.reasoning_capable is True
    assert b.reasoning_control == "unknown"
    assert a.reasoning_split is True
    assert b.reasoning_split is False
    assert len(made) == 2


def test_pool_routed_client_uses_global_baseline_not_default_model_contract(monkeypatch):
    """A model-specific default contract must not leak into unrelated routed models."""
    registry = ProviderRegistry(
        providers={
            "other": ProviderSpec(
                id="other",
                base_url="https://other.invalid/v1",
                api_key_env="X",
                models={"plain-openai": ModelSpec()},
                default_model="plain-openai",
            )
        }
    )
    monkeypatch.setattr(
        ProviderRegistry,
        "client_params",
        lambda self, pid, mid: {
            "api_key": "k",
            "base_url": "https://other.invalid/v1",
            "model": mid,
            # Intentionally omit timeout/max_tokens/wire_protocol: this model has
            # no provider/model override and ModelSpec wire default is OpenAI.
        },
    )
    resolved_default = _default_client()
    resolved_default.timeout_s = 333.0
    resolved_default.max_tokens = 131072
    resolved_default.wire_protocol = "anthropic"

    made: list[SimpleNamespace] = []

    def build_client(**kwargs):
        obj = SimpleNamespace(**kwargs, close=lambda: None)
        made.append(obj)
        return obj

    with mock.patch("llm_loop.llm.pool.LLMClient", side_effect=build_client):
        pool = ModelClientPool(
            registry=registry,
            default_client=resolved_default,  # type: ignore[arg-type]
            base_timeout_s=120.0,
            base_max_tokens=8192,
        )
        routed = pool.get_client("other/plain-openai")

    assert routed.timeout_s == 120.0
    assert routed.max_tokens == 8192
    assert routed.wire_protocol == "openai"
    assert len(made) == 1


def test_route_uses_one_registry_snapshot_for_client_and_model(
    tmp_path, monkeypatch,
):
    """热重载不得夹在 get_client 与 resolve 之间造成“client 已拿到、标签却失败”。"""
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    shared_fake = _FakeLLMClient("deepseek-v4-pro")
    pool = _make_pool(settings, default_fake, cached={"deepseek": shared_fake})
    engine = _make_engine(tmp_path, pool, settings)
    sess = engine.session.load(engine.session.create())

    original_get = pool.get_client

    class _ReloadedRegistry:
        def resolve(self, _ref):
            raise ValueError("registry changed after client lookup")

    def get_then_reload(ref):
        client = original_get(ref)
        pool.registry = _ReloadedRegistry()  # type: ignore[assignment]
        return client

    monkeypatch.setattr(pool, "get_client", get_then_reload)
    decision = engine._route_model("deepseek/deepseek-v4-pro", sess)

    assert decision.final_answer_override is None
    assert decision.llm_client is shared_fake
    assert decision.model_used == "deepseek/deepseek-v4-pro"
    assert decision.chat_model_arg == "deepseek-v4-pro"


def test_route_metadata_uses_same_snapshot_as_override_client(
    tmp_path, monkeypatch,
):
    """override client 已按旧快照选定后即使热切表，context/cpt 也必须来自同一旧快照。"""
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    shared_fake = _FakeLLMClient("deepseek-v4-pro")
    pool = _make_pool(settings, default_fake, cached={"deepseek": shared_fake})
    engine = _make_engine(tmp_path, pool, settings)
    sess = engine.session.load(engine.session.create())
    original_get = pool.get_resolved_client

    replacement = ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={"deepseek-v4-pro": ModelSpec(context=32, thinking=True)},
                default_model="deepseek-v4-pro",
                chars_per_token=0.1,
            )
        }
    )

    def get_then_reload(ref, **kwargs):
        resolved = original_get(ref, **kwargs)
        pool.registry = replacement
        return resolved

    monkeypatch.setattr(pool, "get_resolved_client", get_then_reload)
    decision = engine._route_model("deepseek/deepseek-v4-pro", sess)

    assert decision.final_answer_override is None
    assert decision.llm_client is shared_fake
    assert decision.context_limit == 1_000_000
    assert decision.chars_per_token == 0.6


def test_default_route_metadata_uses_startup_registry_after_reload(
    tmp_path, monkeypatch,
):
    """default client 不热改，因此其context/cpt也必须绑定启动registry，而不是热重载新表。"""
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)
    sess = engine.session.load(engine.session.create())

    pool.registry = ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={"deepseek-v4-flash": ModelSpec(context=64, thinking=True)},
                default_model="deepseek-v4-flash",
                chars_per_token=0.2,
            )
        }
    )
    decision = engine._route_model(None, sess)

    assert decision.llm_client is default_fake
    assert decision.context_limit == 1_000_000
    assert decision.chars_per_token == 0.6


def test_route_binding_precedes_build_reload_and_next_round_sees_new_registry(
    tmp_path, monkeypatch,
):
    """Route/client binds before build; a build-time reload affects only the next round."""
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    old_fake = _FakeLLMClient("deepseek-v4-pro")
    new_fake = _FakeLLMClient("deepseek-v4-pro")
    old_fake.queue([LLMResponse(content="old-snapshot", tool_calls=[], provider="fake")])
    new_fake.queue([LLMResponse(content="new-snapshot", tool_calls=[], provider="fake")])
    pool = _make_pool(settings, default_fake, cached={"deepseek": old_fake})
    engine = _make_engine(tmp_path, pool, settings)
    new_registry = ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={
                    "deepseek-v4-flash": ModelSpec(context=1_000_000, thinking=True),
                    "deepseek-v4-pro": ModelSpec(context=1_000_000, thinking=True),
                },
                default_model="deepseek-v4-flash",
                chars_per_token=0.2,
            )
        }
    )

    original_build = engine._build_llm_messages
    reloaded = False

    def build_then_reload(*args, **kwargs):
        nonlocal reloaded
        built = original_build(*args, **kwargs)
        if not reloaded:
            reloaded = True
            pool.replace_registry(new_registry)
            # 模拟新registry已有自己的cache；旧snapshot本轮不得覆盖它。
            pool._provider_cache["deepseek"] = new_fake  # noqa: SLF001
        return built

    monkeypatch.setattr(engine, "_build_llm_messages", build_then_reload)
    sid = engine.session.create()

    first = engine.run(sid, "first", model="deepseek/deepseek-v4-pro")
    assert first.final_answer == "old-snapshot"
    assert first.model_used == "deepseek/deepseek-v4-pro"
    assert pool._provider_cache["deepseek"] is new_fake  # noqa: SLF001

    second = engine.run(sid, "second", model="deepseek/deepseek-v4-pro")
    assert second.final_answer == "new-snapshot"
    assert pool.registry_snapshot() is new_registry


def test_session_override_same_provider_passes_resolved_model(
    tmp_path, monkeypatch,
):
    """legacy provider-level injected fake 被复用时，session override 也必须显式传裸 model id。"""
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    shared_fake = _FakeLLMClient("deepseek-v4-flash")
    shared_fake.queue([LLMResponse(content="pro", tool_calls=[], provider="fake")])
    pool = _make_pool(settings, default_fake, cached={"deepseek": shared_fake})
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.model_override = "deepseek/deepseek-v4-pro"
    engine.session.save(sess)
    result = engine.run(sid, "你好")

    assert result.model_used == "deepseek/deepseek-v4-pro"
    assert shared_fake.calls[-1]["kwargs"]["model"] == "deepseek-v4-pro"



def test_fallback_same_provider_passes_candidate_model(build_test_engine, fake_settings, monkeypatch):
    """fallback A→B 同 provider 时，即使复用注入 fake，也必须真正请求 B。"""
    import dataclasses

    from llm_loop.llm.errors import LLMHTTPError
    from llm_loop.llm.providers import load_registry
    from tests.conftest import FakeLLM

    def raise_500(_calls):
        raise LLMHTTPError("boom", status_code=500, provider="shared")

    engine, primary = build_test_engine([raise_500])
    monkeypatch.setenv("LLM_API_KEY", "k")
    settings = dataclasses.replace(
        fake_settings,
        model_providers_raw=json.dumps(
            {
                "shared": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://shared.local/v1",
                    "models": {"model-a": {}, "model-b": {}},
                    "default_model": "model-a",
                }
            }
        ),
        model_fallbacks_raw="shared/model-b",
    )
    primary.model = "model-a"
    fallback = FakeLLM([LLMResponse(content="B answer", tool_calls=[], provider="shared")])
    fallback.model = "model-a"
    pool = ModelClientPool(
        registry=load_registry(settings),
        default_client=primary,  # type: ignore[arg-type]
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    pool._provider_cache["shared"] = fallback  # noqa: SLF001 — legacy injected cache compatibility
    engine.settings = settings
    engine.llm_pool = pool

    result = engine.run(engine.session.create(), "hello")
    assert result.final_answer == "B answer"
    assert result.model_used == "shared/model-b"
    assert fallback.calls[-1]["model"] == "model-b"


def test_fallback_guard_budget_uses_same_registry_snapshot_as_candidate_client(
    tmp_path, monkeypatch,
):
    """fallback client 按旧表选定后即使热重载，GuardRequestContext 预算也必须来自同一旧快照。"""
    from llm_loop.core.loop.engine_services.fallback import FallbackService
    from llm_loop.core.loop.engine_services.routing import RoutingService
    from llm_loop.llm.client import LLMClient
    from llm_loop.llm.errors import LLMTimeoutError
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec

    old_registry = ProviderRegistry(
        providers={
            "backup": ProviderSpec(
                id="backup",
                base_url="https://old.invalid/v1",
                api_key_env="",
                models={"m": ModelSpec(context=100_000)},
                default_model="m",
                chars_per_token=1.0,
            )
        }
    )
    new_registry = ProviderRegistry(
        providers={
            "backup": ProviderSpec(
                id="backup",
                base_url="https://new.invalid/v1",
                api_key_env="",
                models={"m": ModelSpec(context=100)},
                default_model="m",
                chars_per_token=0.1,
            )
        }
    )
    default = LLMClient(api_key="k", base_url="https://default.invalid/v1", model="primary")
    pool = ModelClientPool(
        registry=old_registry,
        default_client=default,
        model_fallbacks_raw="backup/m",
    )

    class _Engine(FallbackService, RoutingService):
        def __init__(self):
            self.llm_pool = pool
            self.status = None
            self.corrections = None
            self.settings = SimpleNamespace(data_dir=str(tmp_path))
            self._host = self  # W4-02b: RoutingService 宿主面 = 本假引擎（属性面与原 mixin 需求一致）

        def _runtime_history_budget(self):
            return 1_000_000

        def _record_action(self, *_args, **_kwargs):
            return None

    captured = {}

    def fake_chat(self, **kwargs):
        captured["guard"] = kwargs.get("guard_context")
        return LLMResponse(content="fallback-ok", tool_calls=[], provider="backup")

    monkeypatch.setattr(LLMClient, "chat", fake_chat)
    original_resolved = pool.get_resolved_client

    def get_then_reload(ref, **kwargs):
        resolved = original_resolved(ref, **kwargs)
        pool.replace_registry(new_registry)
        return resolved

    monkeypatch.setattr(pool, "get_resolved_client", get_then_reload)
    engine = _Engine()
    resp, _msgs, ref = engine._try_fallback_chain(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        timeout_s=1.0,
        primary_error=LLMTimeoutError("primary timeout"),
        session_id="s1",
    )

    assert resp is not None and ref == "backup/m"
    assert captured["guard"] is not None
    # old registry snapshot: context=100K, chars/token=1.0, 90% physical
    # input safety boundary => 90K. The former 50K expectation encoded the
    # retired fixed-half-window heuristic.
    assert captured["guard"].history_budget == 90_000
    pool.close()


def test_overflow_feedback_keeps_request_snapshot_window_after_reload(tmp_path, monkeypatch):
    """refresh 后 overflow telemetry 必须报告请求快照窗口，且不恢复 prompt 注入。"""
    from llm_loop.llm.errors import LLMHTTPError
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)
    actions: list[tuple] = []
    monkeypatch.setattr(
        engine, "_record_action", lambda *args, **kwargs: actions.append(args)
    )
    new_registry = ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={"deepseek-v4-flash": ModelSpec(context=64, thinking=True)},
                default_model="deepseek-v4-flash",
                chars_per_token=0.2,
            )
        }
    )

    call_count = 0

    def chat_with_reload(messages, tools, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            pool.replace_registry(new_registry)
            raise LLMHTTPError(
                "context length exceeded", status_code=400, provider="deepseek"
            )
        return LLMResponse(content="after-overflow", tool_calls=[], provider="fake")

    monkeypatch.setattr(default_fake, "chat", chat_with_reload)
    sid = engine.session.create()
    result = engine.run(sid, "hello")
    assert result.final_answer == "after-overflow"
    sess = engine.session.load(sid)
    # R8.24-B: overflow occurrence is telemetry/runtime state only; do not
    # reintroduce model-visible program prose just to satisfy an old test.
    overflow_msgs = [m.content for m in sess.messages if "上下文溢出" in m.content]
    assert overflow_msgs == []
    overflow_actions = [
        a for a in actions if len(a) >= 3 and a[0] == "overflow.compact"
    ]
    assert overflow_actions
    detail = str(overflow_actions[-1][2])
    assert "provider_window=1000000" in detail
    assert "provider_window=64" not in detail


def test_cache_window_uses_request_snapshot_cpt_after_reload(tmp_path, monkeypatch):
    """响应回来前registry已切换时，cache.window边界换算仍必须使用实际请求快照cpt。"""
    from llm_loop.core import cache_window as cache_window_mod
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec
    from tests.unit.test_model_attribution import (
        _FakeLLMClient,
        _make_engine,
        _make_pool,
        _settings,
    )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)
    new_registry = ProviderRegistry(
        providers={
            "deepseek": ProviderSpec(
                id="deepseek",
                base_url="https://new.invalid/v1",
                api_key_env="DEEPSEEK_API_KEY",
                models={"deepseek-v4-flash": ModelSpec(context=1_000_000, thinking=True)},
                default_model="deepseek-v4-flash",
                chars_per_token=0.2,
            )
        }
    )

    def chat_with_reload(messages, tools, **kwargs):
        pool.replace_registry(new_registry)
        return LLMResponse(
            content="ok",
            tool_calls=[],
            provider="fake",
            prompt_tokens=100,
            completion_tokens=5,
            prompt_cache_hit_tokens=50,
        )

    monkeypatch.setattr(default_fake, "chat", chat_with_reload)
    captured = {}
    original = cache_window_mod.describe_cache_window

    def capture_window(*args, **kwargs):
        captured["cpt"] = kwargs.get("chars_per_token")
        return original(*args, **kwargs)

    monkeypatch.setattr(cache_window_mod, "describe_cache_window", capture_window)
    result = engine.run(engine.session.create(), "hello")
    assert result.final_answer == "ok"
    assert captured["cpt"] == 0.6
