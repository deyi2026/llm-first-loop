"""RunFinalizer 同波: LoopEngine 运行时参数 service（W4-02a，M53 拆分件 service 化）.

集中读取本轮循环运行时参数（迭代上限/历史预算/抽取间隔/记忆 top-k/超时），
优先运行时覆盖（runtime override），无则回落配置默认值。
原 _RuntimeParamsMixin（runtime.py，5 法 50 行）逐字平移；宿主面
（runtime/settings/_current_context_limit/_default_model_label）显式经 self._host——
engine 保留 5 委托壳（build/routing/turn_context/attempt_executor/tests 零改动，
D-B5-10② 公开面先例）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from llm_loop.core.history import converge_history_budget  # EVO-20260818: 运行期同源收敛

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

# EVO-20260816-3af5dee3: 字符/token 估算（与 routing._effective_history_budget 同源）
# 2026-08-24 校准（拷问产出）: 2 → 0.6 —— 实测大上下文(>100K tokens) 1.676 tok/char、
# 全量加权 1.230 tok/char；旧值 0.5 低估 3.35 倍 → 上下文守卫形同虚设、缓存边界显示失真
# （688K tokens 实际 ≈41 万字符, 旧估算写成 137 万）。0.6 ≈ 1.67 tok/char 对齐大上下文实测,
# 中小上下文略保守（宁可多拦不漏拦）。
_CHARS_PER_TOKEN_EST = 0.6


class RuntimeParamsService:
    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _runtime_max_iterations(self) -> int:
        """轮数上限（PARAM-01: 动态优先、静态兜底）."""
        if self._host.runtime is not None:
            return self._host.runtime.max_iterations
        return self._host.settings.max_iterations

    def _runtime_history_budget(self) -> int:
        """历史预算诊断值（显式 cap 优先，否则按默认模型物理窗口估算）.

        settings.history_max_chars=None 不再代表一个全局执行 cap。RoutingService 会基于
        当前实际路由模型计算 authoritative effective budget；本方法保留 int 返回仅供
        兼容诊断/旧调用方，不能被当作未配置时的独立限制。
        """
        if self._host.runtime is not None and self._host.runtime.is_overridden("history_budget"):
            dynamic = self._host.runtime.history_max_chars
            if dynamic is not None:
                return dynamic
        configured = getattr(self._host.settings, "history_max_chars", None)
        if configured is not None:
            return configured
        try:
            ctx_lim = getattr(self._host, "_current_context_limit", None)
            def_model = getattr(self._host, "_default_model_label", None)
            if ctx_lim is not None and def_model is not None:
                limit = ctx_lim(def_model())
                if limit:
                    # 未配置全局 cap：这里只返回物理窗口预算的诊断估算；routing 再按
                    # 当前实际模型扣 output reserve/provider cap。
                    return converge_history_budget(None, model_window=limit)[0]
        except Exception:  # noqa: BLE001 — 窗口查询失败兜底旧默认
            pass
        return 100000

    def _runtime_extract_interval(self) -> int:
        """会话状态快照注入间隔（M58 配置面收敛: 动态优先、静态兜底）."""
        if self._host.runtime is not None:
            return self._host.runtime.extract_interval_msgs
        return getattr(self._host.settings, "extract_interval_msgs", 20) or 20

    def _runtime_memory_top_k(self) -> int:
        """记忆检索条数（M57 配置面收敛: 动态优先、静态兜底）."""
        if self._host.runtime is not None:
            return self._host.runtime.memory_top_k
        return getattr(self._host.settings, "memory_top_k", 5)

    def _runtime_timeout(self) -> float | None:
        """LLM 调用超时（PARAM-01: 动态优先、静态兜底）.

        仅当 timeout_s 被显式调整（adjust_strategy / 会话级策略）时才作为
        per-call 覆盖下发; 未调整返回 None → client 使用自身超时
        （provider 级 timeout_s 优先, 否则全局 LLM_TIMEOUT_S）。
        本地慢模型（LM Studio 大上下文 prefill 超 120s）由此获得 provider 级
        更大超时; 未配置 provider 超时时行为与既有完全一致（client 超时即全局值）。
        """
        if self._host.runtime is not None and self._host.runtime.is_overridden("timeout_s"):
            return self._host.runtime.llm_timeout_s
        return None
