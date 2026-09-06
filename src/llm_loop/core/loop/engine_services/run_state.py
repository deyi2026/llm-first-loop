"""RunStateManager——per-session 运行状态桶管理器（B5-W4-03 对象化收尾）.

RunState 显式状态流的桶侧 authority（design T6-A/T6-B-2）：

- 桶生命周期：``_RunState`` 按 session_id 分桶，跨会话并发 run 不共享（P0-5 串台修复语义）
- 会话解析：``current_session_id`` contextvar → 无上下文回退 ``last_active_sid``
  （out-of-run 复查/测试断言语义保持）
- 一致性锁：``guard`` 同时保护本桶表与 engine._run_sessions 绑定表
  （P0-5 原语义单锁跨两结构；events/lifecycle/archive 的直访点已改经本服务）

服务组件间通信一律经 RunState/桶对象，禁止直接读写 engine 实例属性
（design §469 拦截判据）；本服务无 host 引用——自足可测。
"""

from __future__ import annotations

import threading

from llm_loop.core.loop.runstate import _RunState
from llm_loop.core.run_context import current_session_id as _current_session_id


class RunStateManager:
    """会话状态桶管理器（自足服务：无 host 依赖）."""

    def __init__(self) -> None:
        self._buckets: dict[str, _RunState] = {}
        # 原 engine._run_states_guard（P0-5）：桶表 + run 绑定表共用一致性锁
        self.guard = threading.Lock()
        self.last_active_sid: str = ""

    def bucket(self) -> _RunState:
        """当前执行上下文的会话状态桶；无上下文回退最近活跃会话桶（out-of-run 复查）."""
        sid = _current_session_id.get() or self.last_active_sid
        with self.guard:
            return self._buckets.setdefault(sid, _RunState())

    def bound_session_id(self) -> str:
        """Return only the session explicitly bound to the current run context.

        ``last_active_sid`` is diagnostic fallback for bucket inspection only.  It must
        never authorize session-scoped capability selection or ownership checks.
        """
        return str(_current_session_id.get() or "")
