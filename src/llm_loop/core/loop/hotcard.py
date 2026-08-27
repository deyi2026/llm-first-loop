"""任务热卡（Task Hot-Card）——EVO-20260826-81f8f674 任务接力机制.

背景（三个实证）: ①handoff_now 生成空壳（任务状态无数据源接入）；②用户意图只活在
对话流，get_goal 返回陈旧 Goal 引发 2026-08-26 恢复漂移；③超限守卫触发紧急压缩时
程序握有完整上下文却只归档原始历史——黄金窗口浪费。

设计（单一数据源派生，不新增第二套真相）:
- write_hotcard(): 压缩发生时刻（run.compact 审计点）聚合「任务锚点（最近用户指令+
  最近动作, 复用 focus.build_task_anchor）+ active Goal 及最近 checkpoint（复用
  GoalStore）+ pending_review 演进待审」落盘 JSON；fail-open 绝不阻断压缩。
- pop_hotcard(): 新会话 build 尾部注入——仅当「来源会话 ≠ 当前会话且未消费」时取出
  （wrap 由调用方统一），取出即标记 consumed（防陈旧卡反复注入）。
- 恢复冲突语义由 RULE-AI-20 第 7 条兜底: 热卡与用户最新指令冲突时以用户指令为准。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("llm_loop.core.loop.hotcard")

_SCHEMA = 1
_HOTCARD_NAME = "task_hotcard.json"


def hotcard_path(data_dir: str | Path) -> Path:
    """热卡固定落点: <data_dir>/handoff/task_hotcard.json（与手写过渡卡同目录）."""
    return Path(data_dir) / "handoff" / _HOTCARD_NAME


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write_json(path: Path, payload: dict) -> None:
    """原子写（tmp+rename），与 GoalStore 同模式，避免半写损坏."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _load_active_goals(audit_dir: str | Path, limit: int = 3) -> list[dict]:
    """active Goal 摘要（objective + 最近 checkpoint 的 what/next）——复用 GoalStore."""
    try:
        from llm_loop.introspection.goal import GoalStore

        rows = GoalStore(audit_dir).list(status="active", limit=limit)
        out: list[dict] = []
        for r in rows:
            cps = r.get("checkpoints") or []
            if isinstance(cps, str):  # 防御: 旧记录可能为字符串 repr
                cps = []
            last = cps[-1] if cps else {}
            out.append(
                {
                    "id": r.get("id", ""),
                    "objective": str(r.get("objective", ""))[:200],
                    "status": r.get("status", ""),
                    "checkpoint_what": str(last.get("what", ""))[:200],
                    "checkpoint_next": str(last.get("next", ""))[:200],
                }
            )
        return out
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("hotcard: 读取 active goals 失败（fail-open 跳过该字段）", exc_info=True)
        return []


def _load_pending_evolutions(audit_dir: str | Path, limit: int = 3) -> list[str]:
    """pending_review 演进 id（待用户决策项的诚实来源）."""
    try:
        p = Path(audit_dir) / "evolution_suggestions.jsonl"
        if not p.exists():
            return []
        ids: list[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if d.get("status") == "pending_review" and d.get("id"):
                ids.append(str(d["id"]))
        return ids[:limit]
    except Exception:  # noqa: BLE001
        return []


def build_hotcard_payload(
    *,
    origin_session: str,
    anchor: str,
    data_dir: str | Path,
) -> dict:
    """聚合五字段热卡（intent/done 由 anchor 承载，goal/next 由 GoalStore，
    pending 由演进待审）——全部从既有单一数据源派生."""
    data_dir = Path(data_dir)
    audit = data_dir / "audit"
    return {
        "schema": _SCHEMA,
        "ts": _now(),
        "origin_session": origin_session,
        "anchor": anchor,  # 当前任务（最近用户指令）+ 最近动作（focus 提取）
        "active_goals": _load_active_goals(audit),
        "pending_evolutions": _load_pending_evolutions(audit),
        "consumed": False,
        "consumed_by": "",
    }


def write_hotcard(
    *,
    origin_session: str,
    anchor: str,
    data_dir: str | Path,
) -> bool:
    """压缩时刻写热卡（fail-open）: 失败仅告警，绝不阻断压缩主流程."""
    try:
        payload = build_hotcard_payload(
            origin_session=origin_session, anchor=anchor, data_dir=data_dir
        )
        _atomic_write_json(hotcard_path(data_dir), payload)
        return True
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("hotcard: 写入失败（fail-open，不影响压缩）", exc_info=True)
        return False


def _render_card_text(card: dict) -> str:
    """热卡 → 注入文本（调用方再走 wrap_injection 统一包装）."""
    lines = ["[任务热卡] 上一会话压缩时刻的任务接力卡（恢复任务连续性用，非新指令）:"]
    if card.get("anchor"):
        lines.append(f"{card['anchor']}")
    for g in card.get("active_goals") or []:
        line = f"活跃目标: {g.get('objective', '')}（{g.get('id', '')}, {g.get('status', '')}）"
        if g.get("checkpoint_what"):
            line += f"；最近 checkpoint: {g['checkpoint_what']}"
        if g.get("checkpoint_next"):
            line += f"；下一步: {g['checkpoint_next']}"
        lines.append(line)
    if card.get("pending_evolutions"):
        lines.append("待用户决策（演进待审）: " + ", ".join(card["pending_evolutions"]))
    lines.append("若与用户最新指令冲突，以用户最新指令为准（RULE-AI-20 第 7 条）。")
    return "\n".join(lines)


def pop_hotcard(*, session_id: str, data_dir: str | Path) -> str | None:
    """取出未消费且来源会话 ≠ 当前会话的热卡文本，并立即标记 consumed.

    返回 None 的三种情形: 无卡 / 已消费 / 来源即当前会话（同会话压缩已有
    [压缩关键事实] 帧，不重复注入）。
    """
    path = hotcard_path(data_dir)
    try:
        if not path.exists():
            return None
        card = json.loads(path.read_text(encoding="utf-8"))
        if card.get("consumed"):
            return None
        if card.get("origin_session") == session_id:
            return None
        text = _render_card_text(card)
        card["consumed"] = True
        card["consumed_by"] = session_id
        card["consumed_ts"] = _now()
        _atomic_write_json(path, card)
        return text
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("hotcard: 读取/消费失败（fail-open 不注入）", exc_info=True)
        return None


def reset_hotcard_consumed(*, session_id: str, data_dir: str | Path) -> bool:
    """[err1210 T2.2，defer 回存 hotcard 槽] 复位被本会话消费的热卡 consumed 标记.

    身份校验: 仅当 consumed == True 且 consumed_by == session_id 时复位
    （consumed=False、清空 consumed_by/consumed_ts）——防复活已被新压缩事件
    覆盖的陈旧卡。文件缺失/校验不匹配/写失败返回 False（fail-open）。
    复位后下一轮 build pop_hotcard 可再次取出注入（幂等：重复复位返回 False）。
    """
    path = hotcard_path(data_dir)
    try:
        if not path.exists():
            return False
        card = json.loads(path.read_text(encoding="utf-8"))
        if card.get("consumed") is not True or card.get("consumed_by") != session_id:
            return False
        card["consumed"] = False
        card["consumed_by"] = ""
        card.pop("consumed_ts", None)
        _atomic_write_json(path, card)
        return True
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("hotcard: consumed 复位失败（fail-open）", exc_info=True)
        return False
