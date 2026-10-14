"""EVO-20261014-7299aec2: record_use 审计的净分派生视图（只读汇总）。

数据源是两侧既有 usage ledger（methods/usage.jsonl、experiences/usage.jsonl）。
本模块只做派生汇总：不建平行账本、不改写任何记录、不裁决处置——threshold_alert
是提醒即止，invalidated/retired 等处置决策及其独立事实依据要求仍归模型与既有 gate。

预埋口径（提案 D1-D4 的实现锚定）：
- D1 机械汇总：applied/adapted=+1、not_applicable=-1、rejected=-1（RULE-AI-31 计分表）。
  未验证的 applied 默认仍记 +1；纠偏来自 disproven 触发（experience 侧当前
  verification_state），净分本身不按验证态加权——保持机械汇总语义。
- D2 分项展示：a/n/r 计数始终并列出现。not_applicable 与 rejected 同为 -1 但处置
  语义不同——"我用不上 ≠ 它错了"：not_applicable 负分只记账，不构成弃用依据
  （RULE-AI-31 第 3 条）；rejected 才是错误引导证据。
- D3 重锚点：净分只累计"最近一次 lifecycle transition 之后"的声明。锚点取账本条目
  内嵌的声明时 status（method 键 method_status / experience 键 status）与当前 status
  的尾段一致：自最新条目回溯，首个 status 不等处截断。已知边界：status 往返
  （如 archive→restore 回到原 status）在账本上不可分辨，该情形沿用往返前的累计
  ——restore 后历史负证据重新可见，属保守取向；如需清零语义由处置动作自身承担。
- D4 存储路径：沿用 usage.jsonl 两侧既有布局，本模块零新增存储。
"""

from __future__ import annotations

from typing import Any

ALERT_NET_THRESHOLD = -2

_POSITIVE = {"applied", "adapted"}
_NOT_APPLICABLE = {"not_applicable"}  # 计 -1 但只记账，不构成弃用依据（RULE-AI-31）
_REJECTED = {"rejected"}


def summarize_since_last_transition(
    entries_newest_first: list[dict],
    *,
    decision_key: str,
    status_key: str,
    current_status: str,
    disproven: bool = False,
) -> dict[str, Any]:
    """对"最近 lifecycle transition 之后"的声明做机械净分汇总。

    entries 需按最新在前排列（两侧 store 的读取序已在调用点归一）。current_status
    为空（当前卡不可得）时不重锚、全量累计，并在 anchor 中如实标注。
    """
    current = str(current_status or "").strip()
    anchor = "ledger_full"
    kept: list[dict] = []
    if current:
        for entry in entries_newest_first:
            if not isinstance(entry, dict):
                continue
            if str(entry.get(status_key) or "").strip() != current:
                break
            kept.append(entry)
        anchor = f"lifecycle_status({current})"
    else:
        kept = [e for e in entries_newest_first if isinstance(e, dict)]

    counts = {"applied": 0, "not_applicable": 0, "rejected": 0}
    unrecognized = 0
    for entry in kept:
        decision = str(entry.get(decision_key) or "").strip().lower()
        if decision in _POSITIVE:
            counts["applied"] += 1
        elif decision in _NOT_APPLICABLE:
            counts["not_applicable"] += 1
        elif decision in _REJECTED:
            counts["rejected"] += 1
        else:
            unrecognized += 1
    net = counts["applied"] - counts["not_applicable"] - counts["rejected"]
    return {
        "net": net,
        "applied": counts["applied"],
        "not_applicable": counts["not_applicable"],
        "rejected": counts["rejected"],
        "unrecognized": unrecognized,
        "anchor": anchor,
        "disproven": bool(disproven),
    }


def breached(summary: dict[str, Any] | None) -> bool:
    """触发条件：净分 ≤ 阈值，或当前记录 verification_state=disproven（D1 纠偏）。"""
    if not summary:
        return False
    return int(summary.get("net", 0)) <= ALERT_NET_THRESHOLD or bool(summary.get("disproven"))


def detail(summary: dict[str, Any]) -> str:
    """D2：分项计数并列展示，not_applicable 与 rejected 分开可见。"""
    return f"a{summary.get('applied', 0)}/n{summary.get('not_applicable', 0)}/r{summary.get('rejected', 0)}"


def signed_net(summary: dict[str, Any]) -> str:
    return f"{int(summary.get('net', 0)):+d}"


def row_annotation(summary: dict[str, Any] | None) -> dict[str, Any]:
    """search_records 命中行附加字段；无汇总（无使用声明）时不附加任何键。"""
    if not summary:
        return {}
    annotation: dict[str, Any] = {
        "usage_net": int(summary.get("net", 0)),
        "usage_net_detail": detail(summary),
    }
    if breached(summary):
        annotation["pending_disposition"] = True
    return annotation


def alert_section(label: str, ref: str, summary: dict[str, Any] | None) -> str:
    """生命周期工具回执的运行时附加告警段；未触发返回空串（调用方免拼接）。"""
    if not summary or not breached(summary):
        return ""
    triggers = []
    if int(summary.get("net", 0)) <= ALERT_NET_THRESHOLD:
        triggers.append(f"net={summary.get('net', 0)}<={ALERT_NET_THRESHOLD}")
    if summary.get("disproven"):
        triggers.append("verification_state=disproven")
    return (
        f"[threshold_alert] {label} {ref} 使用净分触发（{'；'.join(triggers)}）："
        f"net={signed_net(summary)} [{detail(summary)}] "
        f"unrecognized={summary.get('unrecognized', 0)} anchor={summary.get('anchor', '')}。"
        "提醒即止，处置决策仍归模型（destructive disposition 仍需独立事实依据）；"
        "not_applicable 计 -1 但只记账、不构成弃用依据（rejected 才是错误引导证据）；"
        "applied 未验证默认 +1，disproven 即触发本告警纠偏。"
    )
