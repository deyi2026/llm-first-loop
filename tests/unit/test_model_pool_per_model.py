"""ModelClientPool / route / fallback 的 per-model 真实选路回归。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from llm_loop.config import Settings
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
                    "model-a": ModelSpec(thinking=True),
                    "model-b": ModelSpec(thinking=False),
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
    assert len(made) == 2


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
    decision = engine._route_model(
        "deepseek/deepseek-v4-pro",
        sess,
        [{"role": "user", "content": "hello"}],
        [],
    )

    assert decision.final_answer_override is None
    assert decision.llm_client is shared_fake
    assert decision.model_used == "deepseek/deepseek-v4-pro"
    assert decision.chat_model_arg == "deepseek-v4-pro"


def test_route_guard_metadata_uses_same_snapshot_as_override_client(
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
    seen = {}

    def capture_guard(_messages, _tools, context_limit, _label, *, max_tokens=0, chars_per_token=0.0):
        seen["context"] = context_limit
        seen["cpt"] = chars_per_token
        seen["max_tokens"] = max_tokens
        return None

    monkeypatch.setattr(engine, "_check_context_fit", capture_guard)
    decision = engine._route_model(
        "deepseek/deepseek-v4-pro", sess, [{"role": "user", "content": "hello"}], []
    )

    assert decision.final_answer_override is None
    assert decision.llm_client is shared_fake
    assert seen["context"] == 1_000_000
    assert seen["cpt"] == 0.6


def test_default_route_guard_uses_startup_registry_metadata_after_reload(
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
    seen = {}

    def capture_guard(_messages, _tools, context_limit, _label, *, max_tokens=0, chars_per_token=0.0):
        seen["context"] = context_limit
        seen["cpt"] = chars_per_token
        return None

    monkeypatch.setattr(engine, "_check_context_fit", capture_guard)
    decision = engine._route_model(
        None, sess, [{"role": "user", "content": "hello"}], []
    )

    assert decision.llm_client is default_fake
    assert seen["context"] == 1_000_000
    assert seen["cpt"] == 0.6


def test_engine_round_snapshot_survives_reload_during_message_build(
    tmp_path, monkeypatch,
):
    """refresh夹在build与route之间时，本轮仍用旧snapshot；旧client不得写回新cache，下一轮才切新表。"""
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
    old_registry = pool.registry_snapshot()
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

    original_locked = pool._get_client_locked  # noqa: SLF001 — 断言stale snapshot cache策略
    seen_use_cache: list[tuple[object, bool]] = []

    def observe_get(registry, provider_id, model_id, *, use_cache=True):
        seen_use_cache.append((registry, use_cache))
        if registry is old_registry and not use_cache:
            return old_fake
        return original_locked(
            registry, provider_id, model_id, use_cache=use_cache
        )

    monkeypatch.setattr(pool, "_get_client_locked", observe_get)
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
    assert any(reg is old_registry and use_cache is False for reg, use_cache in seen_use_cache)
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


def test_local_fast_route_passes_fast_model_to_shared_provider_client(
    tmp_path, monkeypatch,
):
    """local 27B→9B fast route 不得只改标签，实际 route.model 参数也必须是 fast。"""
    from tests.unit.test_model_attribution import _FakeLLMClient, _make_engine, _make_pool

    monkeypatch.setenv("LOCAL_API_KEY", "k")
    providers = json.dumps(
        {
            "local": {
                "api_key_env": "LOCAL_API_KEY",
                "base_url": "http://localhost:1234/v1",
                "models": {
                    "large": {"context": 131072, "thinking": True},
                    "fast": {"context": 131072, "thinking": False},
                },
                "default_model": "large",
                "fast_model": "fast",
            }
        }
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="http://localhost:1234/v1",
        llm_model="large",
        data_dir=str(tmp_path / "data"),
        model_providers_raw=providers,
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    default_fake = _FakeLLMClient("large")
    shared_fake = _FakeLLMClient("large")
    pool = _make_pool(settings, default_fake, cached={"local": shared_fake})
    engine = _make_engine(tmp_path, pool, settings)
    engine._focus.reset()
    sess = engine.session.load(engine.session.create())

    decision = engine._route_model(
        None, sess, [{"role": "user", "content": "1+1=?"}], []
    )
    assert decision.model_used == "local/fast"
    assert decision.chat_model_arg == "fast"
    assert decision.llm_client is shared_fake


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
    from llm_loop.core.loop.fallback import _FallbackMixin
    from llm_loop.core.loop.routing import _RoutingMixin
    from llm_loop.llm.client import LLMClient
    from llm_loop.llm.errors import LLMTimeoutError
    from llm_loop.llm.providers import ModelSpec, ProviderRegistry, ProviderSpec

    monkeypatch.setenv("FALLBACK_NOTICE_COOLDOWN_S", "0")

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

    class _Engine(_FallbackMixin, _RoutingMixin):
        def __init__(self):
            self.llm_pool = pool
            self.status = None
            self.corrections = None
            self.settings = SimpleNamespace(data_dir=str(tmp_path))

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
    assert captured["guard"].history_budget == 50_000
    pool.close()


def test_overflow_feedback_keeps_request_snapshot_window_after_reload(tmp_path, monkeypatch):
    """请求期间refresh后，overflow反馈必须报告实际请求快照窗口，而不是新registry元数据。"""
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
    overflow_msgs = [m.content for m in sess.messages if "上下文溢出" in m.content]
    assert overflow_msgs
    assert "1000000" in overflow_msgs[0]
    assert "64" not in overflow_msgs[0]


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
