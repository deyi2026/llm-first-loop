"""飞书文本指令审批（EVO-20260817 飞书审批 UX，方案 A）.

用户经飞书私聊直接审批演进建议，替代终端 CLI（evolve-review）：
- "审批列表" → 列出 pending/accepted 待审建议
- "批准 EVO-xxx" → 状态机 review(accepted)（权限允许自动触发执行）
- "拒绝 EVO-xxx 理由：..." → 状态机 review(rejected)（理由可选）

安全：仅私聊（非群）+ open_id 白名单（feishu_session_map.json p: 前缀 + env 覆盖）。
状态机：EvolutionStore.review（含跨进程 flock 锁）；accepted 后走
maybe_auto_execute_from_engine（与 CLI 共用公共函数，防分叉）。
所有解析/校验 fail-open：非指令 → 返回 None 走原消息路径。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_APPROVAL_LIST_CMDS = {"审批列表", "审批", "列表"}
_APPROVAL_ACCEPT_CMDS = {"批准", "同意", "通过"}
_APPROVAL_REJECT_CMDS = {"拒绝", "驳回"}
_REASON_SEPS = ("理由：", "理由:", "原因：", "原因:", "因为：", "因为:", "，理由", " 理由")


def parse_approval(text: str) -> tuple[str, str, str] | None:
    """解析审批指令 → (cmd, evo_id, reason)；非审批指令 → None.

    cmd ∈ {"list", "accept", "reject"}。规范化：strip/小写匹配指令词，
    精确指令词（防"审批流程怎样"误触发）。
    """
    t = (text or "").strip()
    if not t:
        return None
    # 列表类
    if t in _APPROVAL_LIST_CMDS:
        return ("list", "", "")
    # 批准/拒绝: 首词精确匹配
    first, _, rest = t.partition(" ")
    first = first.strip()
    if first in _APPROVAL_ACCEPT_CMDS:
        evo = _extract_evo_id(rest)
        return ("accept", evo, "") if evo else ("accept", "", "")
    if first in _APPROVAL_REJECT_CMDS:
        evo, reason = _extract_evo_id_with_reason(rest)
        return ("reject", evo, reason) if evo else ("reject", "", "")
    return None


def _extract_evo_id(rest: str) -> str:
    """从剩余文本提取 EVO-xxx id（首个 EVO- 开头的 token）."""
    for tok in rest.split():
        tok = tok.strip().strip("，,。.")
        if tok.startswith("EVO-") and len(tok) > 4:
            return tok
    return ""


def _extract_evo_id_with_reason(rest: str) -> tuple[str, str]:
    """提取 evo_id + 可选理由（拒绝场景）."""
    evo = _extract_evo_id(rest)
    reason = ""
    for sep in _REASON_SEPS:
        if sep in rest:
            _, _, r = rest.partition(sep)
            reason = r.strip()
            break
    return evo, reason


def is_approval_allowed(msg: Any) -> bool:
    """审批权限校验：私聊 + open_id 白名单."""
    if getattr(msg, "is_group", False):
        return False
    sender = getattr(msg, "sender_id", "") or ""
    return bool(sender) and sender in _allowed_open_ids()


def _allowed_open_ids() -> set[str]:
    """白名单：feishu_session_map.json p: 前缀 open_id + env FEISHU_APPROVAL_ALLOWED."""
    out: set[str] = set()
    try:
        base = Path(os.environ.get("DATA_DIR", "data"))
        smap = base / "feishu_session_map.json"
        if smap.exists():
            d = json.loads(smap.read_text(encoding="utf-8"))
            for k, _v in d.items():
                if k.startswith("p:"):
                    out.add(k[2:])
    except Exception:  # noqa: BLE001 — 白名单读取失败 fail-open（空集=全拒绝）
        pass
    env = os.environ.get("FEISHU_APPROVAL_ALLOWED", "").strip()
    if env:
        out.update(oid.strip() for oid in env.split(",") if oid.strip())
    return out


def list_pending(store: Any, limit: int = 5) -> str:
    """列出待审建议（pending_review 优先 + accepted 待执行）."""
    try:
        pending = store.list(status="pending_review") or []
        accepted = store.list(status="accepted") or []
    except Exception:  # noqa: BLE001
        return "⚠️ 读取演进建议失败，请稍后重试。"
    if not pending and not accepted:
        return "📭 当前无待审批建议。"
    lines = ["📋 待审批演进建议："]
    for s in (pending + accepted)[:limit]:
        st = s.get("status", "?")
        prio = s.get("priority", "?")
        title = (s.get("content") or "").replace("\n", " ")[:60]
        lines.append(f"- {s.get('id')} [{st}/{prio}] {title}")
    if len(pending) + len(accepted) > limit:
        lines.append(f"  …共 {len(pending) + len(accepted)} 条，回复「批准/拒绝 EVO-xxx」操作")
    else:
        lines.append("回复「批准 EVO-xxx」或「拒绝 EVO-xxx 理由：…」操作")
    return "\n".join(lines)


def approve(store: Any, evo_id: str) -> tuple[bool, str, bool]:
    """批准：review(accepted)。返回 (ok, 回执文本, 本次是否真正审批)."""
    try:
        cur = _find(store, evo_id)
        if cur is None:
            return False, f"⚠️ 未找到 {evo_id}（可回复「审批列表」查看）", False
        if cur.get("status") in ("executed", "failed", "rolled_back"):
            return False, f"ℹ️ {evo_id} 已处于 {cur.get('status')} 状态，无需重复审批。", False
        if cur.get("status") == "accepted":
            return True, f"ℹ️ {evo_id} 已是 accepted（待执行）状态。", False
        target = store.review(evo_id, "accepted")
        if target is None:
            return False, f"⚠️ 审批失败：未找到 {evo_id}", False
        return True, f"✅ 已批准 {evo_id} → accepted", True
    except Exception as exc:  # noqa: BLE001
        return False, f"⚠️ 审批异常：{type(exc).__name__}: {exc}", False


def reject(store: Any, evo_id: str, reason: str = "") -> tuple[bool, str]:
    """拒绝：review(rejected)，理由落盘 note. 返回 (ok, 回执文本)."""
    try:
        cur = _find(store, evo_id)
        if cur is None:
            return False, f"⚠️ 未找到 {evo_id}（可回复「审批列表」查看）"
        if cur.get("status") in ("executed", "failed", "rolled_back"):
            return False, f"ℹ️ {evo_id} 已处于 {cur.get('status')} 状态，无需拒绝。"
        target = store.review(evo_id, "rejected")
        if target is None:
            return False, f"⚠️ 拒绝失败：未找到 {evo_id}"
        # 理由落盘 note（review() 不接收 note，用 _transition 补充——幂等，不改变状态）
        try:
            if reason:
                store._transition(evo_id, status="rejected", note=reason)
        except Exception:  # noqa: BLE001 — 理由落盘失败不影响拒绝结果
            pass
        return True, f"❌ 已拒绝 {evo_id}" + (f"（理由：{reason}）" if reason else "")
    except Exception as exc:  # noqa: BLE001
        return False, f"⚠️ 拒绝异常：{type(exc).__name__}: {exc}"


def _find(store: Any, evo_id: str) -> dict | None:
    try:
        for s in store.list() or []:
            if s.get("id") == evo_id:
                return s
    except Exception:  # noqa: BLE001
        return None
    return None


def handle_approval(engine: Any, msg: Any, text: str, reply_fn: Any) -> bool:
    """飞书审批指令入口（handlers._handle_text 调用）.

    Returns: True=已处理（含拒绝授权）；False=非审批指令走原路径。
    reply_fn 签名: (receive_id, text, receive_id_type)（对齐 handlers._reply_fn）。
    审批完成后按 EVOLVE_LOCAL_EXEC 自动执行（与 CLI 共用公共函数）。
    """
    parsed = parse_approval(text)
    if parsed is None:
        return False
    cmd, evo_id, reason = parsed
    rid, rtype = getattr(msg, "reply_receive_id", ""), getattr(msg, "reply_receive_id_type", "")
    if not is_approval_allowed(msg):
        reply_fn(rid, "⚠️ 无权执行审批指令（仅限本人私聊）。", rtype)
        return True
    store = getattr(engine, "evolution_store", None)
    if store is None:
        reply_fn(rid, "⚠️ 演进功能未启用（EVOLVE_ENABLED=0）。", rtype)
        return True
    if cmd == "list":
        reply_fn(rid, list_pending(store), rtype)
        return True
    if cmd == "accept":
        ok, resp, reviewed = approve(store, evo_id)
        if ok and reviewed and evo_id:
            # 本次真正审批 → 按权限自动执行（与 CLI evolve-review 行为一致）
            from llm_loop.introspection.evolution_exec import maybe_auto_execute_from_engine

            cur = _find(store, evo_id)
            if cur is not None:
                try:
                    resp += "\n" + maybe_auto_execute_from_engine(engine, store, cur)
                except Exception as exc:  # noqa: BLE001 — 执行失败不影响审批结果
                    resp += f"\n⚠️ 自动执行触发异常：{type(exc).__name__}"
        reply_fn(rid, resp, rtype)
        return True
    if cmd == "reject":
        ok, resp = reject(store, evo_id, reason)
        reply_fn(rid, resp, rtype)
        return True
    return False
