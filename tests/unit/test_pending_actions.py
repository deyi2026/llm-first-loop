"""pending_actions 维度测试（spec.md 5.3.1 / design.md §2.5 / tasks.md T4.5）.

断言:
1. snapshot() 返回含 pending_actions 字段且结构合法
2. 数据源正常时计数值正确（非 null）
3. 数据源失败时计数字段为 null + note 标注原因（fail-open 不伪造 0）
4. pending_actions 是纯聚合（无副作用：调用前后系统状态不变）
5. 未注入回调时返回 {"note": "数据源未注入"}（向后兼容）
"""

from __future__ import annotations

import pytest

from llm_loop.introspection.status import ArchitectureStatusProvider


@pytest.fixture
def provider() -> ArchitectureStatusProvider:
    return ArchitectureStatusProvider()


class TestPendingActionsField:
    def test_snapshot_contains_pending_actions(self, provider):
        snap = provider.snapshot()
        assert "pending_actions" in snap

    def test_no_callback_returns_not_injected_note(self, provider):
        snap = provider.snapshot()
        assert snap["pending_actions"] == {"note": "数据源未注入"}

    def test_dimension_filter_includes_pending_actions(self, provider):
        snap = provider.snapshot(dimensions=["pending_actions"])
        assert "pending_actions" in snap


class TestPendingActionsAggregation:
    def test_callback_returns_aggregated_values(self, provider):
        provider.set_pending_actions_fn(lambda: {
            "executing_evolutions": 2,
            "pending_reviews": 1,
            "pending_self_evals": 0,
            "hint": "2 项演进执行中",
            "note": None,
        })
        pa = provider.snapshot()["pending_actions"]
        assert pa["executing_evolutions"] == 2
        assert pa["pending_reviews"] == 1
        assert pa["pending_self_evals"] == 0
        assert pa["hint"] == "2 项演进执行中"

    def test_callback_failure_fail_open_null_not_zero(self, provider):
        def bad_fn():
            raise RuntimeError("boom")
        provider.set_pending_actions_fn(bad_fn)
        pa = provider.snapshot()["pending_actions"]
        assert pa["executing_evolutions"] is None
        assert pa["pending_reviews"] is None
        assert pa["pending_self_evals"] is None
        assert pa["hint"] is None
        assert "boom" in pa["note"]

    def test_callback_failure_type_in_note(self, provider):
        def bad_fn():
            raise ValueError("store missing")
        provider.set_pending_actions_fn(bad_fn)
        pa = provider.snapshot()["pending_actions"]
        assert "ValueError" in pa["note"]


class TestPureAggregation:
    def test_no_side_effects_single_call(self, provider):
        calls: list[int] = []

        def fn():
            calls.append(1)
            return {"executing_evolutions": 0, "pending_reviews": 0,
                    "pending_self_evals": 0, "hint": None, "note": None}

        provider.set_pending_actions_fn(fn)
        before = len(calls)
        provider.snapshot()
        assert len(calls) == before + 1

    def test_snapshot_does_not_mutate_provider_state(self, provider):
        provider.set_pending_actions_fn(lambda: {
            "executing_evolutions": 5, "pending_reviews": 3,
            "pending_self_evals": 1, "hint": "test", "note": None,
        })
        phase_before = provider._current_phase
        trace_before = len(provider._action_trace)
        provider.snapshot()
        assert provider._current_phase == phase_before
        assert len(provider._action_trace) == trace_before


class TestFactoryPendingActionsFn:
    def test_build_pending_actions_fn_aggregates(self, tmp_path):
        from llm_loop.factory import _build_pending_actions_fn

        class FakeSettings:
            audit_dir = tmp_path

        fn = _build_pending_actions_fn(FakeSettings())
        result = fn()
        assert result["executing_evolutions"] == 0
        assert result["pending_reviews"] == 0
        assert result["pending_self_evals"] == 0
        assert result["hint"] is None

    def test_build_pending_actions_fn_fail_open(self, tmp_path, monkeypatch):
        import llm_loop.introspection.evolution as ev_module
        from llm_loop.factory import _build_pending_actions_fn

        class BoomStore:
            def __init__(self, *a, **kw):
                raise RuntimeError("store init failed")

            def list(self):
                return []

        monkeypatch.setattr(ev_module, "EvolutionStore", BoomStore)

        class FakeSettings:
            audit_dir = tmp_path

        fn = _build_pending_actions_fn(FakeSettings())
        result = fn()
        assert result["executing_evolutions"] is None
        assert result["note"] is not None
