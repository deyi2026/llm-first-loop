"""LoopEngine 运行时参数 mixin（M53 拆分: loop.py 1087 行→按职责分文件，纯重构行为零变化）.

集中读取本轮循环运行时参数（迭代上限/历史预算/抽取间隔/记忆 top-k/超时），
优先运行时覆盖（runtime override），无则回落配置默认值。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


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
# EVO-20260811-10dc2533 L3: 小窗口注入联动阈值（与 routing._SMALL_WINDOW_TOKENS
# 同值异名——避免 runtime→routing 的 mixin 循环 import，语义同源注释锚定）
_SMALL_WINDOW_TOPK_TOKENS = 32768


class _RuntimeParamsMixin:
    def _runtime_max_iterations(self: LoopEngine) -> int:
        """轮数上限（PARAM-01: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.max_iterations
        return self.settings.max_iterations

    def _runtime_history_budget(self: LoopEngine) -> int:
        """上下文注入预算（PARAM-01: 动态优先、静态兜底）.

        EVO-20260816-3af5dee3: settings.history_max_chars=None（未显式配置）时
        按当前模型窗口 8% 自适应（取代固定 100K——1M 窗口下 100K 仅 10% 过保守，
        262K 窗口下 100K 达 38% 偏激进）。窗口未知兜底旧默认 100000。
        """
        if self.runtime is not None:
            return self.runtime.history_max_chars
        configured = getattr(self.settings, "history_max_chars", None)
        if configured is not None:
            return configured
        try:
            ctx_lim = getattr(self, "_current_context_limit", None)
            def_model = getattr(self, "_default_model_label", None)
            if ctx_lim is not None and def_model is not None:
                limit = ctx_lim(def_model())
                if limit:
                    # EVO-20260818: 与装配期同源收敛（converge_history_budget——兜底 100K / 上限 200K）
                    return converge_history_budget(None, model_window=limit)[0]
        except Exception:  # noqa: BLE001 — 窗口查询失败兜底旧默认
            pass
        return 100000

    def _runtime_extract_interval(self: LoopEngine) -> int:
        """会话状态快照注入间隔（M58 配置面收敛: 动态优先、静态兜底）."""
        if self.runtime is not None:
            return self.runtime.extract_interval_msgs
        return getattr(self.settings, "extract_interval_msgs", 20) or 20

    def _runtime_memory_top_k(self: LoopEngine) -> int:
        """记忆检索条数（M57 配置面收敛: 动态优先、静态兜底）.

        EVO-20260811-10dc2533 L3: 小窗口注入联动——默认模型窗口 <32K 时 top_k
        降档（≥8K→2，<8K→1），防记忆注入挤占本地小窗口模型预算。fail-open:
        窗口感知失败（无 pool/未知模型/异常）回退 base，零回归。
        """
        base: int
        if self.runtime is not None:
            base = self.runtime.memory_top_k
        else:
            base = getattr(self.settings, "memory_top_k", 5)
        if base <= 1:
            return base
        try:
            limit_fn = getattr(self, "_current_context_limit", None)
            label_fn = getattr(self, "_default_model_label", None)
            if limit_fn is not None and label_fn is not None:
                limit = limit_fn(label_fn())
                if limit and limit < _SMALL_WINDOW_TOPK_TOKENS:
                    return min(base, 2 if limit >= 8192 else 1)
        except Exception:  # noqa: BLE001 — 窗口感知 fail-open，感知失败回退 base
            pass
        return base

    def _runtime_timeout(self: LoopEngine) -> float | None:
        """LLM 调用超时（PARAM-01: 动态优先、静态兜底）.

        仅当 timeout_s 被显式调整（adjust_strategy / 会话级策略）时才作为
        per-call 覆盖下发; 未调整返回 None → client 使用自身超时
        （provider 级 timeout_s 优先, 否则全局 LLM_TIMEOUT_S）。
        本地慢模型（LM Studio 大上下文 prefill 超 120s）由此获得 provider 级
        更大超时; 未配置 provider 超时时行为与既有完全一致（client 超时即全局值）。
        """
        if self.runtime is not None and self.runtime.is_overridden("timeout_s"):
            return self.runtime.llm_timeout_s
        return None
