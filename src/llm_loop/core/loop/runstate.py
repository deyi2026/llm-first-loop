"""P0-5(2026-08-15): per-run 状态分桶 mixin（审计发现 #7 —— LoopEngine 可重入修复）.

从 engine.py 拆出（对齐 M53 职责 mixin 拆分纪律，守卫 engine.py 体量）：

- ``_RunState``: 单个会话的可变运行状态（停滞指纹/overflow 计数/预警标志/
  快照节流/breakdown/build_info），按 session_id 分桶，跨会话并发 run 不共享。
- ``_RunStateMixin``: 属性 shim——既有 ``self._stagnation_state`` 等读写接口不变
  （零回归），实际按 ``run_context.current_session_id`` 解析到本会话桶；
  无上下文（out-of-run 复查/测试断言）回退 ``_last_active_sid`` 桶。

依赖宿主提供（engine __init__ 初始化）：
``self._run_states: dict[str, _RunState]`` / ``self._run_states_guard`` /
``self._last_active_sid: str``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_loop.core.run_context import current_session_id as _current_session_id


@dataclass
class _RunState:
    """单个会话一次/多次 run 的可变运行状态（按 session_id 分桶，跨会话不共享）.

    - stagnation_state: 实时停滞指纹追踪（engine/tool_exec 共用）
    - overflow_reinject_count: overflow 反馈注入次数（同一 run 最多 1 次）
    - context_warning_injected / round_warning_injected: 预警一次性标志
    - last_snapshot_count: 会话状态快照节流（跨 run 保留——同会话多次 run 共享节流语义）
    - last_breakdown / last_build_info: 上下文占用分解快照（architecture_status 消费）
    """

    stagnation_state: dict = field(
        default_factory=lambda: {"fp": None, "count": 0, "reminded": False}
    )
    overflow_reinject_count: int = 0
    context_warning_injected: bool = False
    round_warning_injected: bool = False
    exhaustion_decision_used: bool = False  # 轮次耗尽决策轮一次性标志（2026-08-15）
    last_snapshot_count: int = 0
    last_breakdown: Any = None
    last_build_info: Any = None


class _RunStateMixin:
    """per-run 状态属性 shim（接口不变，落到当前会话桶；审计发现 #7 串台修复）."""

    # 宿主属性（engine __init__ 初始化），此处仅为类型标注
    _run_states: dict[str, _RunState]
    _run_states_guard: Any
    _last_active_sid: str

    def _run_state(self) -> _RunState:
        """当前执行上下文的会话状态桶；无上下文回退最近活跃会话桶（out-of-run 复查）."""
        sid = _current_session_id.get() or self._last_active_sid
        with self._run_states_guard:
            return self._run_states.setdefault(sid, _RunState())

    @property
    def _stagnation_state(self) -> dict:
        return self._run_state().stagnation_state

    @_stagnation_state.setter
    def _stagnation_state(self, value: dict) -> None:
        self._run_state().stagnation_state = value

    @property
    def _overflow_reinject_count(self) -> int:
        return self._run_state().overflow_reinject_count

    @_overflow_reinject_count.setter
    def _overflow_reinject_count(self, value: int) -> None:
        self._run_state().overflow_reinject_count = value

    @property
    def _context_warning_injected(self) -> bool:
        return self._run_state().context_warning_injected

    @_context_warning_injected.setter
    def _context_warning_injected(self, value: bool) -> None:
        self._run_state().context_warning_injected = value

    @property
    def _round_warning_injected(self) -> bool:
        return self._run_state().round_warning_injected

    @_round_warning_injected.setter
    def _round_warning_injected(self, value: bool) -> None:
        self._run_state().round_warning_injected = value

    @property
    def _exhaustion_decision_used(self) -> bool:
        return self._run_state().exhaustion_decision_used

    @_exhaustion_decision_used.setter
    def _exhaustion_decision_used(self, value: bool) -> None:
        self._run_state().exhaustion_decision_used = value

    @property
    def _last_snapshot_count(self) -> int:
        return self._run_state().last_snapshot_count

    @_last_snapshot_count.setter
    def _last_snapshot_count(self, value: int) -> None:
        self._run_state().last_snapshot_count = value

    @property
    def _last_breakdown(self) -> Any:
        return self._run_state().last_breakdown

    @_last_breakdown.setter
    def _last_breakdown(self, value: Any) -> None:
        self._run_state().last_breakdown = value

    @property
    def _last_build_info(self) -> Any:
        return self._run_state().last_build_info

    @_last_build_info.setter
    def _last_build_info(self, value: Any) -> None:
        self._run_state().last_build_info = value
