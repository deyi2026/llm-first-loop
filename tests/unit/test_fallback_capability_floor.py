"""R8.24 D'-3.2: fallback capability floor 链序与静默替换断言（D-G6 / D-G7——用户指定验证门）.

- D-G6: 自动链成员低于 capability floor = 0（enforce 态链构造过滤单测）。
- D-G7: 用户显式选定模型被静默替换 = 0（strict 显式 override——engine
  is_default_assembled 判定静态断言 + 行为断言）。
- 同模型优先重试计数 ≤2（D'-2.3 ②——D-D6-5）。
- shadow 态链行为零变化 + would_downgrade_below_floor 观测事件在场。

M 状态红线（test_fallback_integration 等 4 项）零触碰——本文件独立。
"""

# pyright: reportAttributeAccessIssue=false
# (mixin 模式: _same_model_retry_before_fallback 的 self 来自 LoopEngine 装配，
#  与 fallback.py 文件级关闭惯例一致)

import inspect
import logging
import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from llm_loop.llm.client import LLMClient
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import (
    ModelSpec,
    ProviderRegistry,
    ProviderSpec,
    is_below_capability_floor,
)


def _registry(*models: tuple[str, str, str]) -> ProviderRegistry:
    """构造测试注册表: (provider_id, model_id, capability_tier) 三元组列表."""
    provs: dict[str, ProviderSpec] = {}
    for pid, mid, tier in models:
        spec = provs.setdefault(
            pid,
            ProviderSpec(
                id=pid, base_url="http://x.invalid/v1", api_key_env="LFL_TEST_KEY"
            ),
        )
        spec.models[mid] = ModelSpec(capability_tier=tier)
    return ProviderRegistry(providers=provs)


def _pool(registry: ProviderRegistry, fallbacks: str) -> ModelClientPool:
    return ModelClientPool(
        registry=registry,
        default_client=cast(LLMClient, object()),  # fallback_candidates 不消费 default_client
        model_fallbacks_raw=fallbacks,
    )


class TestFloorPredicate:
    """D'-2.1: capability_tier → floor 判据映射（strong 进链/weak 不进/unknown 保守不进）."""

    def test_strong_not_below(self):
        assert is_below_capability_floor(ModelSpec(capability_tier="strong")) is False

    def test_weak_below(self):
        assert is_below_capability_floor(ModelSpec(capability_tier="weak")) is True

    def test_unknown_below_conservative(self):
        assert is_below_capability_floor(ModelSpec(capability_tier="unknown")) is True

    def test_default_is_unknown_conservative(self):
        """ModelSpec 缺省 capability_tier=unknown——保守视为弱模型."""
        assert ModelSpec().capability_tier == "unknown"
        assert is_below_capability_floor(ModelSpec()) is True


class TestShadowChainUnchanged:
    """D'-2.2: shadow 默认——链行为与现状零变化 + 观测事件在场."""

    def test_shadow_keeps_below_floor_candidates(self, monkeypatch, caplog):
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.delenv("LFL_FALLBACK_FLOOR", raising=False)
        reg = _registry(("strongp", "big", "strong"), ("weakp", "small9b", "weak"))
        pool = _pool(reg, "strongp/big,weakp/small9b")
        with caplog.at_level(logging.INFO, logger="llm_loop.llm.pool"):
            out = pool.fallback_candidates(registry=reg)
        assert out == ["strongp/big", "weakp/small9b"]  # 链不变（shadow 不拦截）
        assert "event=fallback.would_downgrade_below_floor" in caplog.text
        assert "ref=weakp/small9b" in caplog.text
        assert "capability_tier=weak" in caplog.text

    def test_shadow_no_event_for_strong(self, monkeypatch, caplog):
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.delenv("LFL_FALLBACK_FLOOR", raising=False)
        reg = _registry(("strongp", "big", "strong"))
        pool = _pool(reg, "strongp/big")
        with caplog.at_level(logging.INFO, logger="llm_loop.llm.pool"):
            pool.fallback_candidates(registry=reg)
        assert "would_downgrade_below_floor" not in caplog.text


class TestEnforceChainFiltered:
    """D-G6: enforce 态自动链成员低于 floor = 0."""

    def test_enforce_filters_below_floor(self, monkeypatch):
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.setenv("LFL_FALLBACK_FLOOR", "enforce")
        reg = _registry(
            ("strongp", "big", "strong"),
            ("weakp", "small9b", "weak"),
            ("unknownp", "mystery", "unknown"),
        )
        pool = _pool(reg, "strongp/big,weakp/small9b,unknownp/mystery")
        out = pool.fallback_candidates(registry=reg)
        assert out == ["strongp/big"]  # D-G6 主断言: 链内低于 floor = 0
        assert "weakp/small9b" not in out and "unknownp/mystery" not in out

    def test_enforce_filter_logged_not_silent(self, monkeypatch, caplog):
        """剔除有如实日志（floor_filtered 事件——不静默吞）."""
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.setenv("LFL_FALLBACK_FLOOR", "enforce")
        reg = _registry(("weakp", "small9b", "weak"))
        pool = _pool(reg, "weakp/small9b")
        with caplog.at_level(logging.INFO, logger="llm_loop.llm.pool"):
            pool.fallback_candidates(registry=reg)
        assert "event=fallback.floor_filtered" in caplog.text
        assert "ref=weakp/small9b" in caplog.text

    def test_enforce_exhausted_falls_back_to_full_chain(self, monkeypatch, caplog):
        """全部候选低于 floor → 回退原链（防空链死锁——回退现状可回滚）."""
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.setenv("LFL_FALLBACK_FLOOR", "enforce")
        reg = _registry(("weakp", "a", "weak"), ("weakp", "b", "unknown"))
        pool = _pool(reg, "weakp/a,weakp/b")
        with caplog.at_level(logging.INFO, logger="llm_loop.llm.pool"):
            out = pool.fallback_candidates(registry=reg)
        assert out == ["weakp/a", "weakp/b"]  # 回退原链
        assert "event=fallback.floor_exhausted" in caplog.text

    def test_d6_scenario_weak_in_chain_marked(self, monkeypatch):
        """对照 D6 死循环场景: 9B 档（weak）在链中可被标记/过滤."""
        monkeypatch.setenv("LFL_TEST_KEY", "k-test")
        monkeypatch.setenv("LFL_FALLBACK_FLOOR", "enforce")
        reg = _registry(
            ("local", "qwen-9b-q4", "weak"), ("cloud", "flash", "strong")
        )
        pool = _pool(reg, "local/qwen-9b-q4,cloud/flash")
        out = pool.fallback_candidates(registry=reg)
        assert "local/qwen-9b-q4" not in out
        assert out == ["cloud/flash"]


class TestDG7NoSilentReplacement:
    """D-G7: 用户显式选定模型被静默替换 = 0（strict 显式 override）."""

    def test_strict_branch_declared_in_engine(self):
        """静态断言: engine strict 判定（is_default_assembled）+ 用户选择权声明在场."""
        from llm_loop.core.loop import engine

        src = inspect.getsource(engine)
        assert "is_default_assembled = (" in src
        assert "用户选择权" in src  # D'-2.3 ③ 强化声明（用户选择权 > 能力下限）
        assert "sess.model_override is None and chat_model_arg is None" in src

    def test_floor_not_applied_to_model_override(self):
        """静态断言: floor 过滤仅作用于 fallback_candidates（自动装配链）——
        get_client(model_override) 路径无 floor 消费（显式选择不被替换）."""
        from llm_loop.llm import pool as pool_mod

        src = inspect.getsource(pool_mod)
        assert "_apply_capability_floor" in src
        # floor 只在 fallback_candidates 链路被调用；get_client/_get_client_locked 无 floor
        gc_src = inspect.getsource(pool_mod.ModelClientPool.get_client)
        assert "is_below_capability_floor" not in gc_src
        assert "_apply_capability_floor" not in gc_src

    def test_engine_fallback_gated_by_default_assembled(self):
        """行为断言: _try_fallback_chain 调用点在 is_default_assembled 分支内
        （override 在场时静默换链路径不可达）."""
        from llm_loop.core.loop import engine

        src = inspect.getsource(engine)
        fallback_call = src.index("self._try_fallback_chain(")
        gate = src.index("is_default_assembled = (")
        strict_else = src.index("elif not _e1210_recovered:")
        assert gate < fallback_call < strict_else


class TestSameModelRetryBounded:
    """D'-2.3 ②: 同模型优先重试计数 ≤2（D-D6-5 限次防循环）."""

    def _engine_stub(self, tool_messages: bool):
        """最小 engine stub——mixin 方法仅依赖 _runtime_timeout/_cache_monitor/_record_action."""
        from llm_loop.core.loop.fallback import _FallbackMixin
        from llm_loop.core.message import Message, MessageSource

        class _CacheMonitor:
            def breaker_active_for(self, _sid: str) -> bool:
                return False

        class _Stub(_FallbackMixin):
            def _runtime_timeout(self):
                return 1.0

            def _record_action(self, *a, **k):
                pass

            _cache_monitor = _CacheMonitor()

            class _Sess:
                def __init__(self, with_tool: bool):
                    role = "tool" if with_tool else "user"
                    self.messages = [
                        Message(
                            role=role,  # type: ignore[arg-type]
                            content="x",
                            source=MessageSource.TOOL if with_tool else MessageSource.USER,
                        )
                    ]
                    self.session_id = "s-test"

            sess = _Sess(tool_messages)

        return _Stub()

    def test_retry_count_capped_at_two(self, monkeypatch):
        """重试耗尽: chat 恰被调用 max=2 次（≤2 断言）后返回 None 进链."""
        monkeypatch.delenv("LFL_SAME_MODEL_RETRY_MAX", raising=False)
        calls = {"n": 0}

        class _FlakyClient:
            def chat(self, **kwargs):
                calls["n"] += 1
                raise RuntimeError("transient")

        stub = self._engine_stub(tool_messages=True)
        out = stub._same_model_retry_before_fallback(
            sess=stub.sess,
            messages=[{"role": "user", "content": "x"}],
            tools_param=None,
            llm_client=_FlakyClient(),
            chat_model_arg=None,
            session_id="s-test",
            effective_budget=1000,
            rounds=1,
        )
        assert out is None
        assert calls["n"] == 2  # ≤2（默认上限）

    def test_retry_disabled_by_env_zero(self, monkeypatch):
        """LFL_SAME_MODEL_RETRY_MAX=0 → 不重试（回退现状: 失败直接进链）."""
        monkeypatch.setenv("LFL_SAME_MODEL_RETRY_MAX", "0")
        calls = {"n": 0}

        class _FlakyClient:
            def chat(self, **kwargs):
                calls["n"] += 1
                raise RuntimeError("transient")

        stub = self._engine_stub(tool_messages=True)
        out = stub._same_model_retry_before_fallback(
            sess=stub.sess,
            messages=[{"role": "user", "content": "x"}],
            tools_param=None,
            llm_client=_FlakyClient(),
            chat_model_arg=None,
            session_id="s-test",
            effective_budget=1000,
            rounds=1,
        )
        assert out is None
        assert calls["n"] == 0

    def test_no_retry_without_wip_artifacts(self, monkeypatch):
        """无进行中产物（纯对话会话）→ 不重试（行为=现状零变化）."""
        monkeypatch.delenv("LFL_SAME_MODEL_RETRY_MAX", raising=False)
        calls = {"n": 0}

        class _Client:
            def chat(self, **kwargs):
                calls["n"] += 1
                return object()

        stub = self._engine_stub(tool_messages=False)
        out = stub._same_model_retry_before_fallback(
            sess=stub.sess,
            messages=[{"role": "user", "content": "x"}],
            tools_param=None,
            llm_client=_Client(),
            chat_model_arg=None,
            session_id="s-test",
            effective_budget=1000,
            rounds=1,
        )
        assert out is None
        assert calls["n"] == 0

    def test_retry_success_returns_response(self, monkeypatch):
        """重试成功 → 返回响应（调用方落回正常路径，不进 fallback 链）."""
        monkeypatch.delenv("LFL_SAME_MODEL_RETRY_MAX", raising=False)
        sentinel = object()

        class _FlakyThenOk:
            def __init__(self):
                self.n = 0

            def chat(self, **kwargs):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("transient")
                return sentinel

        stub = self._engine_stub(tool_messages=True)
        out = stub._same_model_retry_before_fallback(
            sess=stub.sess,
            messages=[{"role": "user", "content": "x"}],
            tools_param=None,
            llm_client=_FlakyThenOk(),
            chat_model_arg=None,
            session_id="s-test",
            effective_budget=1000,
            rounds=1,
        )
        assert out is sentinel
