"""AttemptExecutor——attempt 规划职责面（provider planning / budget 预取）（R9 Phase 5 T6-A）.

B5-W2-02 迁入：engine._run_stream_inner 规划段（planned_label 解析 /
effective_budget 预取链：窗口感知 → overflow 收缩 → 归因 → 工具轮零历史/预算上限 →
note/记录）装配为 plan(model, sess, planning_registry) -> AttemptResult 门面。
语句逐字平移，``self.`` → ``self._host.``（宿主 = LoopEngine；_planned_model_label /
_effective_history_budget* / _set_model_label_ctx / _note_tool_round_budget /
_record_action / _runtime_history_budget / _overflow_shrink_factor 全留宿主域）。
行为零变化：

- build 阶段（_build_llm_messages）与 routing 决策（_route_model）留宿主主循环，
  AttemptResult 字段 → build 传参面零变化（planned_label / effective_budget /
  tool_round_zero 原名原语义）
- LLM 调用点（payload 构建 + stream 获取）与 routing 元组/两个 break 逃生深耦合，
  归装挂账 W5 波次（RunCoordinator 组装）；_RoutingMixin 已退役为 RoutingService（W4-02b，宿主面经壳不变，D-B5-7 依据保留）

宿主依赖（engine 持有）：_planned_model_label / _set_model_label_ctx /
_effective_history_budget / _effective_history_budget_detail /
_note_tool_round_budget / _record_action / _runtime_history_budget /
_overflow_shrink_factor / _last_budget_info（写回宿主面字段）
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (host 属性来自 LoopEngine 混入体系，pyright 无法静态解析，文件级关闭这两条；
#   沿 recovery_controller.py 既有豁免口径)

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine


@dataclass
class AttemptResult:
    """单次 attempt 规划产物（→ build 阶段传参面，W4 扩展流/路由字段）."""

    planned_label: str
    effective_budget: int
    tool_round_zero: bool
    tool_budget: int
    is_local_tool: bool


class AttemptExecutor:
    """attempt 规划域（W4 补 LLM 调用点 execute/open_stream 归装）."""

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def plan(
        self,
        model: str | None,
        sess: Any,
        planning_registry: Any,
    ) -> AttemptResult:
        """规划本 attempt 的模型标签与有效预算（主循环规划段逐字平移）."""
        # M54: 模型窗口感知的主动压缩 — 先定模型标签, 再按其同一快照窗口收紧历史预算
        planned_label = self._host._planned_model_label(
            model, sess, registry_snapshot=planning_registry
        )
        self._host._set_model_label_ctx(planned_label)
        effective_budget = self._host._effective_history_budget(
            planned_label, registry_snapshot=planning_registry
        )
        # R8.24-B B-2.2/B-D5: overflow 确定性收缩消费点——首次 overflow 后
        # _overflow_shrink_factor 生效（预算收紧 → build 链重组，超出部分走
        # 既有 lossless 归档链；程序侧确定性 compaction，零 prompt 注入）。
        _shrink = getattr(self._host, "_overflow_shrink_factor", None)
        if _shrink is not None and effective_budget:
            effective_budget = int(effective_budget * _shrink)
        # P0-B: 预算归因（architecture_status.context_usage.budget 消费）
        self._host._last_budget_info = self._host._effective_history_budget_detail(
            planned_label, registry_snapshot=planning_registry
        )
        _tb = int(os.environ.get("TOOL_ROUND_BUDGET", "8000"))
        _last_tool = next((bool(getattr(m, "tool_calls", None))
                           for m in reversed(sess.messages) if m.role == "assistant"), False)
        _is_local_tool = _last_tool and planned_label.split("/", 1)[0] == "local"
        # 2026-08-24: 工具轮零历史开关 = env TOOL_ROUND_ZERO_HISTORY 显式 > provider 级
        # tool_round_zero_history 配置（local 已配 true → 工具轮极小窗口默认启用;
        # 云端不配 → False 零回归）。零历史 = 只发 system+工具 schema+最近完整协议
        # 配对组 → KV 前缀稳定命中 + prefill 秒级（本地实测 4-13 tokens prefill 0.2-0.8s）
        _zero_env = os.environ.get("TOOL_ROUND_ZERO_HISTORY")
        if _zero_env is None and planning_registry is not None and "/" in planned_label:
            _spec_tmp = planning_registry.providers.get(planned_label.split("/", 1)[0])
            _zero_env = "1" if (_spec_tmp is not None and _spec_tmp.tool_round_zero_history) else "0"
        _tool_round_zero = _is_local_tool and (_zero_env or "0") == "1"  # noqa: E501
        if _tool_round_zero:
            effective_budget = min(effective_budget, 4000)
        elif _tb > 0 and _is_local_tool:
            effective_budget = min(effective_budget, _tb)
        self._host._note_tool_round_budget(
            _tool_round_zero, _is_local_tool, _tb, effective_budget
        )
        if effective_budget < self._host._runtime_history_budget():
            self._host._record_action(
                "understand.build_messages",
                "model_aware_budget",
                f"{planned_label}: {self._host._runtime_history_budget()}→{effective_budget}",
            )
        return AttemptResult(
            planned_label=planned_label,
            effective_budget=effective_budget,
            tool_round_zero=_tool_round_zero,
            tool_budget=_tb,
            is_local_tool=_is_local_tool,
        )
