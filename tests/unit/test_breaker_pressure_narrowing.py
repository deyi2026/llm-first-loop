"""R8.24 D'-3.3: breaker pressure 终止条件收窄断言（D-G8——用户指定验证门）.

- D-G8 主断言: LFL_BREAKER_PRESSURE_NARROW 缺省或显式 =1 时
  _breaker_pressure_block 因内部 budget 水位终止 run = 0
  （返回 None + observability 事件在场）。
- 显式 =0 保留旧拦截行为，作为可回滚兼容锚点。
- 允许终止 run 的三类（真实 provider window 超限/用户成本/安全）各自单测在场:
  * 真实 window 超限 → test_overflow_lifecycle.py / overflow_action == "end" 路径
    （M 红线既有面——本文件静态断言接线在场，不修改）
  * 安全（privacy）→ test_cache_block_reclassification.py D-G5 双态断言
  * 用户成本 → 成本政策为运营参数面（本批无独立终止点——D-D5 声明
    budget=optimizer；本文件断言其不在 breaker 终止路径内）

M 红线（test_overflow_feedback/test_overflow_lifecycle/test_exhaustion_decision）零触碰。
"""

import inspect
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from llm_loop.core.loop.build import _BuildMixin
from llm_loop.core.message import Message, MessageSource


class _CacheMonitor:
    """breaker/cache monitor stub——可编程 breaker 与压力判定."""

    def __init__(self, *, breaker: bool, pressure: bool):
        self._breaker = breaker
        self._pressure = pressure
        self.pressure_notes: list[dict] = []

    def breaker_active_for(self, _sid: str) -> bool:
        return self._breaker

    def context_pressure_decision(self, _sid: str, chars: int, budget: int) -> bool:
        return self._pressure

    def note_context_pressure(self, sid: str, **kw) -> None:
        self.pressure_notes.append({"session_id": sid, **kw})


class _StubEngine(_BuildMixin):
    """最小 engine stub——_breaker_pressure_block 依赖面."""

    def __init__(self, *, breaker: bool, pressure: bool):
        self._cache_monitor = _CacheMonitor(breaker=breaker, pressure=pressure)
        self.actions: list[tuple] = []

    def _record_action(self, *args) -> None:
        self.actions.append(args)


class _Sess:
    def __init__(self, big_history: bool = True):
        self.session_id = "s-brk"
        self.history_anchors = {"local": 0}
        self.messages = (
            [
                Message(
                    role="user",
                    content="x" * 5000,
                    source=MessageSource.USER,
                )
            ]
            if big_history
            else []
        )


def _run(monkeypatch, narrow: str | None, *, breaker=True, pressure=True):
    if narrow is None:
        monkeypatch.delenv("LFL_BREAKER_PRESSURE_NARROW", raising=False)
    else:
        monkeypatch.setenv("LFL_BREAKER_PRESSURE_NARROW", narrow)
    eng = _StubEngine(breaker=breaker, pressure=pressure)
    out = eng._breaker_pressure_block(_Sess(), effective_budget=1000, planned_label="local/qwen")
    return eng, out


class TestDG8NarrowModeNoTermination:
    """D-G8: 收窄态内部 budget 水位不终止 run."""

    def test_default_is_narrow(self, tmp_path, monkeypatch, caplog):
        """P3.3-B: 未配置开关时默认观测放行，不再把性能水位升级成任务终止。"""
        with caplog.at_level(logging.INFO, logger="llm_loop.core.loop.build"):
            eng, out = _run(monkeypatch, None)
        assert out is None
        assert "event=breaker.context_pressure_narrowed" in caplog.text
        assert any(a[1] == "breaker_context_pressure_narrowed" for a in eng.actions)

    def test_narrow_returns_none(self, tmp_path, monkeypatch, caplog):
        """主断言: 超安全水位 + breaker active + 收窄态 → 返回 None（run 不终止）."""
        with caplog.at_level(logging.INFO, logger="llm_loop.core.loop.build"):
            eng, out = _run(monkeypatch, "1")
        assert out is None  # D-G8: 终止 = 0
        assert "event=breaker.context_pressure_narrowed" in caplog.text

    def test_narrow_records_observability(self, tmp_path, monkeypatch):
        """水位信息降 observability: narrowed action + note_context_pressure 在场."""
        eng, out = _run(monkeypatch, "1")
        assert out is None
        assert any(a[1] == "breaker_context_pressure_narrowed" for a in eng.actions)
        assert eng._cache_monitor.pressure_notes, "note_context_pressure 须在场"

    def test_narrow_no_advisory_wording(self, tmp_path, monkeypatch):
        """指令性输出取消: 收窄态不产生'请先执行压缩 checkpoint/换会话'文案."""
        _, out = _run(monkeypatch, "1")
        assert out is None  # 文案载体（返回 str）已消失——指令面移交 compaction 链


class TestExplicitLegacyRollback:
    """显式 0 保留旧阻断行为，作为兼容/回滚锚点."""

    def test_explicit_zero_returns_block_copy(self, tmp_path, monkeypatch):
        eng, out = _run(monkeypatch, "0")
        assert out is not None
        assert "上下文压力" in out
        assert any(a[1] == "breaker_context_pressure" for a in eng.actions)

    def test_no_breaker_returns_none_all_states(self, tmp_path, monkeypatch):
        """breaker 未激活 → 默认/显式两态均放行."""
        for narrow in (None, "0", "1"):
            _, out = _run(monkeypatch, narrow, breaker=False)
            assert out is None, f"narrow={narrow}"

    def test_no_pressure_returns_none_all_states(self, tmp_path, monkeypatch):
        """水位未超 → 默认/显式两态均放行."""
        for narrow in (None, "0", "1"):
            _, out = _run(monkeypatch, narrow, pressure=False)
            assert out is None, f"narrow={narrow}"


class TestLegalTerminationSet:
    """允许终止 run 的仅三类——各自单测在场（引用既有面 + 静态断言）."""

    def test_window_overflow_termination_path_exists(self):
        """①真实 provider window 超限: overflow end 路径在场（既有
        test_overflow_lifecycle.py 为 M 红线——此处静态断言不修改）."""
        from llm_loop.core.loop import engine

        src = inspect.getsource(engine)
        assert 'overflow_action == "end"' in src
        assert '_run_end_reason = "overflow"' in src

    def test_privacy_safety_termination_path_exists(self):
        """③安全: privacy BLOCK 路径在场（行为断言见 test_cache_block_reclassification
        .TestDG5PrivacyBlockRetained 双态）."""
        from llm_loop.cache_guard import guard as guard_mod

        src = inspect.getsource(guard_mod._check_privacy)
        assert 'verdict="BLOCK"' in src

    def test_cost_policy_not_in_breaker_path(self):
        """②用户成本: 成本政策为运营参数面（D-D5 budget=optimizer）——不属于
        breaker 终止路径（本批无独立成本终止点——预算数值零调整）."""
        src = inspect.getsource(_BuildMixin._breaker_pressure_block)
        assert "cost" not in src.lower() or "optimizer" in src
        # breaker 终止面只判内部水位；成本/预算数值不进终止判定
        assert "LFL_BREAKER_PRESSURE_NARROW" in src

    def test_engine_run_end_reason_wiring_intact(self):
        """显式 0 回滚接线在场: 文案非空 → breaker_context_pressure 仍可收口."""
        from llm_loop.core.loop import engine

        src = inspect.getsource(engine)
        assert '_run_end_reason = "breaker_context_pressure"' in src
