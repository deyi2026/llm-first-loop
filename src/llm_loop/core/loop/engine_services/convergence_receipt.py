"""R2 收敛回执三件套纯函数组装器（antidrift_impl 批 1，design §2.4.2）.

纯机械文本组装，无 IO：
- ``[run_vitals]`` —— run 级事实三值（真相源=engine 主循环局部计数的桶侧镜像，
  与 request.usage/LoopResult 同源；不可得→``unavailable(reason=…)``，禁默认值冒充）。
- ``[self_history_mirror]`` —— 本 run 内此前 convergence_decide(continue) 的
  unresolved 原文镜像：纯列表拼接逐字投影（零相似度/零摘要/零挑选）；
  预算封顶从最旧截断，``truncated_oldest_count`` 常驻=实际截断条数（CT-8 契约
  逐字继承）；单条超预算冻结——至"仅剩最新 1 条"时保留该条全文（保真优先于
  预算，与 history 预算穿透同纪律）。
- ``[queue_pressure]`` —— 等待投递集 {queued, interject_pending} 计数与最早
  入队时间（DC-1 术语映射口径）。

口径登记：``entries={M}`` 为镜像累积全部条目数，``truncated_oldest_count={K}``
为被截断数，渲染清单=最新 M-K 条（机械自洽）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime

DEFAULT_MIRROR_BUDGET_CHARS = 8192


def mirror_budget_chars() -> int:
    """镜像段总字符预算（纯机械常量，OQ2 裁定：缺省 8192，env 可配）."""
    raw = (os.environ.get("LFL_CONVERGENCE_MIRROR_BUDGET_CHARS") or "").strip()
    if not raw:
        return DEFAULT_MIRROR_BUDGET_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MIRROR_BUDGET_CHARS
    return value if value > 0 else DEFAULT_MIRROR_BUDGET_CHARS


@dataclass
class VitalsFacts:
    rounds: int = 0
    wall_clock_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    usage_available: bool = True
    unavailable_reason: str = ""


@dataclass
class MirrorFacts:
    entries: list[str] = field(default_factory=list)


@dataclass
class QueuePressureFacts:
    count: int = 0
    oldest_enqueued_at: float | None = None
    unavailable_reason: str = ""


def _project_mirror_entries(entries: list[str], budget_chars: int) -> tuple[list[str], int]:
    """从最旧截断；返回（可见条目, 实际截断条数）。最新 1 条冻结保留全文。"""
    n = len(entries)
    if n == 0:
        return [], 0
    total = len(entries[n - 1])
    start = n - 1
    for i in range(n - 2, -1, -1):
        cost = len(entries[i])
        if total + cost > budget_chars:
            break
        total += cost
        start = i
    return entries[start:], start


def _render_vitals(v: VitalsFacts) -> str:
    if not v.usage_available:
        reason = v.unavailable_reason.strip() or "usage_unavailable"
        return f"[run_vitals] unavailable(reason={reason})"
    return (
        f"[run_vitals] rounds={v.rounds}; wall_clock_s={v.wall_clock_s:.0f}; "
        f"tokens_in={v.tokens_in}; tokens_out={v.tokens_out}; source=request.usage"
    )


def _render_mirror(m: MirrorFacts, budget_chars: int) -> str:
    visible, truncated = _project_mirror_entries(m.entries, budget_chars)
    lines = [
        f"[self_history_mirror] entries={len(m.entries)}; "
        f"truncated_oldest_count={truncated}"
    ]
    for i, entry in enumerate(visible, 1):
        lines.append(f"{i}. {entry}")
    return "\n".join(lines)


def _render_queue_pressure(q: QueuePressureFacts) -> str:
    if q.unavailable_reason:
        return f"[queue_pressure] unavailable(reason={q.unavailable_reason})"
    if q.count <= 0:
        return "[queue_pressure] waiting_count=0; oldest_enqueued_at=none"
    stamp = (
        datetime.fromtimestamp(q.oldest_enqueued_at).isoformat()
        if q.oldest_enqueued_at is not None
        else "none"
    )
    return f"[queue_pressure] waiting_count={q.count}; oldest_enqueued_at={stamp}"


def render_convergence_receipt_addendum(
    vitals: VitalsFacts,
    mirror: MirrorFacts,
    queue_pressure: QueuePressureFacts,
    *,
    budget_chars: int | None = None,
) -> str:
    """三件套追加段（段间单个空行；调用方负责与既有判定行之间的单个空行拼接）."""
    budget = mirror_budget_chars() if budget_chars is None else budget_chars
    return "\n\n".join(
        [
            _render_vitals(vitals),
            _render_mirror(mirror, budget),
            _render_queue_pressure(queue_pressure),
        ]
    )
