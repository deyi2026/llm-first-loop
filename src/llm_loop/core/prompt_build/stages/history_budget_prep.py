"""历史预算准备阶段（design T5-C 第二批 / B4-C2-03①）.

archive_sink 装配 + effective_budget 解析（R1 中间值）+ EVO-20260817
预算分级 nudge（80% 准备态/90% 压缩态，EVO-20260824-54d46549 双轨
force/growth 增长率门控）+ 渐进折叠 env 配置。compact_ratio 语义
fail-open：异常回退 1.0（不触发分级）。decision.history_total_chars
就地写（P1-01 显式化位）。
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.core.prompt_build.context import BuildDecision


@dataclass(slots=True)
class HistoryBudgetPrep:
    """预算准备产出（compact_ratio/fold_k 进投影调用；nudge 状态调用点回写）."""

    archive_sink: Any = None
    effective_budget: int = 0
    compact_ratio: float = 1.0
    fold_k: int = 0
    last_nudge_total: Any = None


def run_history_budget_prep(
    *,
    sess_messages: list[Any],
    provider_id: str,
    sess_anchor: Any,
    max_chars: int | None,
    runtime_history_budget: Callable[[], int],
    archive: Any,
    registry: Any,
    archive_sink_cb: Any,
    decision: BuildDecision,
    record_action: Callable[..., Any],
    last_nudge_total: Any,
    provider_visible_chars: Callable[..., int],
    growth_nudge_kind: Callable[..., str | None],
) -> HistoryBudgetPrep:
    """archive_sink/budget/nudge/fold_k 装配（产出投影调用前置值）."""
    prep = HistoryBudgetPrep()
    if archive is not None or getattr(
        registry, "evidence_history_capture_enabled", False
    ):
        prep.archive_sink = archive_sink_cb
    # R1: 存构建中间值，供主循环在 tools_param 构造后计算 breakdown（含 tool_schema_chars）
    prep.effective_budget = (
        max_chars if max_chars is not None else runtime_history_budget()
    )
    # EVO-20260817: 预算分级管理——①80% 准备态（审计提示，不压缩）:
    # 长任务大几率撞顶，接近预算时让 AI 感知"下轮可能主动整理压缩"（压缩仍保留
    # 关键事实帧+档案零丢失，不打断推理）；②90% 压缩态（compact_ratio, env 可调）:
    # 预算附近提前平滑压缩（裁到 COMPRESS_TARGET_RATIO 留缓冲），优于撞顶被动压缩。
    try:
        _history_total = decision.history_total_chars = provider_visible_chars(
            sess_messages, provider_id, sess_anchor
        )
        _compact_ratio = float(os.environ.get("COMPACT_RATIO", "0.9"))
        if 0 < _compact_ratio < 1.0:
            # EVO-20260824-54d46549 增长率 nudge（billion-context 拷问产出, 双轨）:
            # - 强制轨: 超预算×compact_ratio（90% 默认）→ 必预警（压缩在即, bypass 增长率）
            # - 增长率轨: 80% 准备态 → 距上次预警增长 ≥ 阈值（预算×5% 或 20K 字符）才预警
            #   （重任务增长快早提示, 普通对话增长慢不打扰——替换原固定 80% 每轮必警）
            _force_at = prep.effective_budget * _compact_ratio
            _prep_at = prep.effective_budget * 0.8
            _growth_floor = max(
                int(prep.effective_budget * 0.05),
                int(os.environ.get("NUDGE_GROWTH_CHARS", "20000")),
            )
            _prev_total = last_nudge_total
            _kind = growth_nudge_kind(
                _history_total,
                _prev_total,
                prep_at=_prep_at,
                force_at=_force_at,
                growth_floor=_growth_floor,
            )
            if _kind == "force":
                record_action(
                    "understand.compact_prep",
                    "approaching_budget",
                    f"history {_history_total} 字符 超预算×{_compact_ratio}（{int(_force_at)}），"
                    f"本轮/下轮触发主动压缩整理；压缩保留关键事实帧+档案零丢失，不影响推理",
                )
                prep.last_nudge_total = _history_total
            elif _kind == "growth" and _prev_total is not None:
                _growth = _history_total - int(_prev_total)
                record_action(
                    "understand.compact_prep",
                    "growth_nudge",
                    f"history {_history_total} 字符 ≥预算 80%（{int(_prep_at)}），"
                    f"距上次预警增长 {_growth} ≥ {_growth_floor}（增长率门控触发）——"
                    f"下一轮可能在 {int(_force_at)} 触发主动压缩整理；"
                    "压缩保留关键事实帧+档案零丢失，不影响推理",
                )
                prep.last_nudge_total = _history_total
    except Exception:  # noqa: BLE001
        _compact_ratio = 1.0
    prep.compact_ratio = _compact_ratio
    # EVO-20260824-54d46549 渐进折叠配置（env, 默认关零回归）: PROGRESSIVE_FOLD_K>0 时
    # 压缩改为"每次最多折最老 K 个配对组"（平滑曲线 + guard 不 BLOCK + 智力无断崖）
    prep.fold_k = int(os.environ.get("PROGRESSIVE_FOLD_K", "0"))
    return prep
