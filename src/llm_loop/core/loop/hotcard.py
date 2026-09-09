"""任务热卡（Task Hot-Card）——EVO-20260826-81f8f674 任务接力机制.

背景（三个实证）: ①handoff_now 生成空壳（任务状态无数据源接入）；②用户意图只活在
对话流，get_goal 返回陈旧 Goal 引发 2026-08-26 恢复漂移；③超限守卫触发紧急压缩时
程序握有完整上下文却只归档原始历史——黄金窗口浪费。

设计（单一数据源派生，不新增第二套真相）:
- write_hotcard(): 压缩发生时刻（run.compact 审计点）聚合「任务锚点（最近用户指令+
  最近动作, 复用 focus.build_task_anchor）+ active Goal 及最近 checkpoint（复用
  GoalStore）+ pending_review 演进待审」落盘 JSON；fail-open 绝不阻断压缩。
- pop_hotcard(): 仅供**已获用户输入侧授权**的显式恢复路径取出。跨会话/未消费
  只是可用性条件，不是授权；默认调用返回 None 且不改变 consumed 状态。
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


def _render_card_text(card: dict, *, ref_path: str = "") -> str:
    """Hot-card automatic projection: one status line + one retrievable file ref.

    R3 keeps the full structured card on disk and stops inlining anchor/goal/checkpoint
    prose. R4 still owns recovery-boundary semantics and consumption/replay policy.
    """
    goals = len(card.get("active_goals") or [])
    pending = len(card.get("pending_evolutions") or [])
    anchor_present = 1 if str(card.get("anchor", "") or "").strip() else 0
    line1 = (
        f"[任务热卡] 上一会话任务接力资料已保存；"
        f"anchor={anchor_present}; active_goals={goals}; pending_review={pending}。"
    )
    ref = str(ref_path or "task_hotcard.json")
    return f"{line1}\nref=file:{ref}"


def pop_hotcard(*, session_id: str, data_dir: str | Path, authorized: bool = False) -> str | None:
    """显式授权后取出未消费且来源会话 ≠ 当前会话的热卡文本.

    R8.14/E24: ``origin_session != session_id`` 只能证明跨会话，不能证明用户要继续
    那个任务。调用方必须先经输入侧 accept/restore 获得授权，再传 ``authorized=True``。
    未授权调用不读取/消费卡，避免普通新会话把陈旧 handoff 自动升级成 prompt authority。

    授权后仍返回 None 的情形: 无卡 / 已消费 / 来源即当前会话。
    """
    if not authorized:
        return None
    path = hotcard_path(data_dir)
    try:
        if not path.exists():
            return None
        card = json.loads(path.read_text(encoding="utf-8"))
        if card.get("consumed"):
            return None
        if card.get("origin_session") == session_id:
            return None
        text = _render_card_text(card, ref_path=str(path))
        card["consumed"] = True
        card["consumed_by"] = session_id
        card["consumed_ts"] = _now()
        _atomic_write_json(path, card)
        return text
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("hotcard: 读取/消费失败（fail-open 不注入）", exc_info=True)
        return None


def reset_hotcard_consumed(
    *, session_id: str, data_dir: str | Path, authorized: bool = False
) -> bool:
    """显式授权恢复路径复位被本会话消费的热卡 consumed 标记.

    R8.14/E24 后 err1210 不再调用本函数。调用方必须先取得用户恢复授权，并传
    ``authorized=True``；否则返回 False 且不改文件。授权后仍执行身份校验：仅当
    consumed == True 且 consumed_by == session_id 时复位
    （consumed=False、清空 consumed_by/consumed_ts）——防复活已被新压缩事件
    覆盖的陈旧卡。文件缺失/校验不匹配/写失败返回 False（fail-open）。
    复位只恢复显式 handoff 可读性，不赋予 build/prompt authority。
    """
    if not authorized:
        return False
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
