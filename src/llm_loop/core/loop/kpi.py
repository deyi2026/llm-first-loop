"""EVO-20260822-9fde48f1 第 10 条: KPI 统计 mixin——注入治理效果可测（对比基线用）.

设计: engine 防膨胀守卫（test_loop_mixin_split.test_complexity_reduction）要求
超预算逻辑拆分到新 mixin。KPI 三件套:
  ① 注入占比（注入字符/提交总字符, build 后累计）
  ② 本地模型平均决策耗时（local provider 轮 LLM 耗时均值）
  ③ 无工具调用轮数（绕路代理指标: AI 停下未调工具）
run.end 统一落盘（响应式, 不推送 LLM——方案第 7 条）。fail-open 零回归。
"""

from __future__ import annotations


class _KpiMixin:
    """run 级 KPI 统计（注入治理前后对比基线）."""

    def _kpi_reset(self) -> None:
        """每次 run 开始重置 KPI 累计器."""
        self._kpi_inject_msgs = 0
        self._kpi_inject_chars = 0
        self._kpi_total_chars = 0
        self._kpi_local_llm_ms = 0.0
        self._kpi_local_rounds = 0
        self._kpi_no_tool_rounds = 0

    def _kpi_accumulate_inject(self) -> None:
        """build 后累计注入占比（读取 _last_inject_stats, 响应式不推送）."""
        _s = getattr(self, "_last_inject_stats", None) or {}
        self._kpi_inject_msgs += int(_s.get("inject_msgs", 0))
        self._kpi_inject_chars += int(_s.get("inject_chars", 0))
        self._kpi_total_chars += int(_s.get("total_chars", 0))

    def _kpi_accumulate_llm(self, planned_label: str, llm_round_ms: float) -> None:
        """LLM 调用后累计本地模型决策耗时（仅 local provider 轮计入）."""
        if planned_label.split("/", 1)[0] == "local":
            self._kpi_local_llm_ms += llm_round_ms
            self._kpi_local_rounds += 1

    def _kpi_note_no_tool(self) -> None:
        """无工具调用轮数 +1（绕路代理指标: AI 停下未调工具）."""
        self._kpi_no_tool_rounds += 1

    # ── 模型标签上下文（EVO-20260822-b3e7105e 注入逻辑, 抽离自 engine 防膨胀）──
    def _save_model_label_ctx(self) -> str:
        """run 入口保存当前模型标签（恢复用）."""
        from llm_loop.core.run_context import current_model_label

        return current_model_label.get()

    def _set_model_label_ctx(self, planned_label: str) -> None:
        """每轮 planned_label 注入 contextvar——工具输出分层按模型预算联动."""
        from llm_loop.core.run_context import current_model_label

        current_model_label.set(planned_label)

    def _restore_model_label_ctx(self, prev: str) -> None:
        """run 结束恢复模型标签（finally 路径）."""
        from llm_loop.core.run_context import current_model_label

        current_model_label.set(prev)

    def _kpi_snapshot(self) -> dict:
        """run.end 落盘用 KPI 快照（不推送 LLM, 方案第 7 条响应式）."""
        return {
            "kpi_inject_msgs": self._kpi_inject_msgs,
            "kpi_inject_ratio": (
                round(self._kpi_inject_chars / self._kpi_total_chars, 4)
                if self._kpi_total_chars
                else 0.0
            ),
            "kpi_local_llm_ms_avg": (
                round(self._kpi_local_llm_ms / self._kpi_local_rounds, 1)
                if self._kpi_local_rounds
                else 0.0
            ),
            "kpi_no_tool_rounds": self._kpi_no_tool_rounds,
        }
