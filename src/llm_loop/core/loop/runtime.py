"""LoopEngine 运行时参数 mixin（M53 拆分: loop.py 1087 行→按职责分文件，纯重构行为零变化）.

集中读取本轮循环运行时参数（迭代上限/历史预算/抽取间隔/记忆 top-k/超时），
优先运行时覆盖（runtime override），无则回落配置默认值。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine


class _RuntimeParamsMixin:
    def _runtime_max_iterations(self: LoopEngine) -> int:
        """轮数上限（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.max_iterations
        return self.settings.max_iterations

    def _runtime_history_budget(self: LoopEngine) -> int:
        """上下文注入预算（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.history_max_chars
        return self.settings.history_max_chars

    def _runtime_extract_interval(self: LoopEngine) -> int:
        """会话状态快照注入间隔（M58 配置面收敛: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.extract_interval_msgs
        return getattr(self.settings, "extract_interval_msgs", 20) or 20

    def _runtime_memory_top_k(self: LoopEngine) -> int:
        """记忆检索条数（M57 配置面收敛: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.memory_top_k
        return getattr(self.settings, "memory_top_k", 5)

    def _runtime_timeout(self: LoopEngine) -> float | None:
        """LLM 调用超时（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.llm_timeout_s
        return None
