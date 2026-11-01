"""跨会话 goal 协作仲裁（DESIGN-20261101 §4.3 写侧归属 + 读侧归属标注）.

真值源: docs/design/DESIGN-20261101-cross-session-coordination-v1.md §4.3/§5

职责（只读判定 + 文案；不写存储、不改 goal 状态）:
1. ``resolve_write_permission``: 返回 (decision, reason_code)，decision ∈
   {allow, allow_annotated, deny}；判定顺序与文档一致（owner 空 → 同会话 →
   显式跨会话授权 → 拒绝）。
2. 拒绝文案含 owner 会话与三条可执行出口（只读 / 显式授权 / 移交归属）。
3. 读侧归属字段派生（owner_session_id / owned_by / claimed_by_other）与恢复横幅。

会话身份真值源: ``bound_session_id()``（contextvar 绑定）。不使用 ``ctx.session_id``
这类 last-writer 字段作授权依据。

已知与文档的差异（诚实登记，见 DESIGN §11-D1 补充）:
- 当前执行无 session binding（bound_session_id 为空，如离线 CLI/单测装配）时，
  文档未定义该态；本实现取 ``allow_annotated / session_unverified``，理由是硬拒会
  锁死既有单会话流程（A9 零回归）。真实运行态 contextvar 必有值，该分支不可达。
"""

from __future__ import annotations


DENY_REASON = "cross_session_write_denied"
REASON_OWNER_UNKNOWN = "owner_unknown"
REASON_CROSS_AUTHORIZED = "cross_session_authorized"
REASON_SESSION_UNVERIFIED = "session_unverified"

DECISION_ALLOW = "allow"
DECISION_ALLOW_ANNOTATED = "allow_annotated"
DECISION_DENY = "deny"


def authority_session_id() -> str:
    """当前执行上下文绑定的 session id（空=不可证明）。"""
    try:
        from llm_loop.introspection.tools_status import bound_session_id

        return str(bound_session_id() or "")
    except Exception:  # noqa: BLE001 — 绑定不可用 → 视为未知，由判定层给出标注
        return ""


def mask_session(session_id: str) -> str:
    sid = str(session_id or "")
    if not sid:
        return ""
    return sid if len(sid) <= 8 else f"{sid[:8]}…"


def _override_authorized(args: dict | None) -> bool:
    """显式跨会话授权：cross_session=true + 非空 reason + 非空 evidence_refs。"""
    if not isinstance(args, dict):
        return False
    if args.get("cross_session") is not True:
        return False
    reason = str(args.get("reason") or "").strip()
    refs = args.get("evidence_refs") or []
    if not reason:
        return False
    return isinstance(refs, (list, tuple)) and any(str(r or "").strip() for r in refs)


def resolve_write_permission(
    goal: dict | None,
    *,
    session_id: str | None = None,
    args: dict | None = None,
) -> dict:
    """§4.3 判定。返回 dict: decision / reason_code / owner_session_id / current_session_id ..."""
    sid = authority_session_id() if session_id is None else str(session_id or "")
    owner = str((goal or {}).get("session_id") or "")
    base = {
        "owner_session_id": owner,
        "owner_masked": mask_session(owner),
        "current_session_id": sid,
        "current_masked": mask_session(sid),
    }
    if goal is None:
        # 存在性由调用方既有分支负责；此处不臆造结论
        return {**base, "decision": DECISION_ALLOW, "reason_code": "", "note": ""}
    if not owner:
        return {
            **base,
            "decision": DECISION_ALLOW_ANNOTATED,
            "reason_code": REASON_OWNER_UNKNOWN,
            "note": (
                "reason_code=owner_unknown；该 goal 无 owner（legacy/未认领），"
                "本次写入按 owner_unknown 标注放行"
            ),
        }
    if sid and sid == owner:
        return {**base, "decision": DECISION_ALLOW, "reason_code": "", "note": ""}
    if not sid:
        return {
            **base,
            "decision": DECISION_ALLOW_ANNOTATED,
            "reason_code": REASON_SESSION_UNVERIFIED,
            "note": (
                "reason_code=session_unverified；当前执行无 session binding，"
                "无法证明是本 goal owner "
                f"（owner={base['owner_masked']}），按 session_unverified 标注放行"
            ),
        }
    if _override_authorized(args):
        return {
            **base,
            "decision": DECISION_ALLOW_ANNOTATED,
            "reason_code": REASON_CROSS_AUTHORIZED,
            "note": (
                "reason_code=cross_session_authorized；显式跨会话授权"
                "（cross_session=true + reason + evidence_refs）放行该写入"
            ),
        }
    return {**base, "decision": DECISION_DENY, "reason_code": DENY_REASON, "note": ""}


def write_refusal_text(gid: str, perm: dict, *, supports_cross_session: bool = True) -> str:
    """§4.3 拒绝回执模板（必须指路，且只指真实存在的出口）。

    supports_cross_session=False 时必须不提 cross_session 参数（P1-5）：
    任务类工具不接收该参数，给出不存在的出口会让模型陷入"按提示重试→仍被拒"的循环。
    """
    owner = perm.get("owner_masked") or "?"
    cur = perm.get("current_masked") or "<无 binding>"
    if supports_cross_session:
        exit2 = (
            "  2) 显式跨会话写入：同一调用加 cross_session=true + reason=\"<为什么必须由你写>\""
            " + evidence_refs=[\"evidence://...\"]\n"
        )
    else:
        exit2 = (
            "  2) 本工具没有跨会话出口（task_* 不接受 cross_session 参数）："
            "请由 owner 会话推进该任务图\n"
        )
    return (
        f"[跨会话写入拒绝] reason_code={perm.get('reason_code') or DENY_REASON}\n"
        f"goal {gid} 属于会话 {owner}（owner），当前会话 {cur}。\n"
        "出口：\n"
        f"  1) 只读查看：get_goal(goal_id=\"{gid}\") / task_frontier(goal_id=\"{gid}\")"
        "（回执标注归属）\n"
        f"{exit2}"
        "  3) 移交归属：由 owner 会话调用 transfer_goal（P2，未实现前请在 owner 会话推进）\n"
        "收口门（任务图/证据门）未被绕过，本条仅拦归属；本次写入未被接受，goal 记录未改。"
    )


def ownership_fields(goal: dict | None, *, session_id: str | None = None) -> dict:
    """读侧归属字段（§4.3 get_goal 标注要求）。只追加新字段，不改既有字段。"""
    perm = resolve_write_permission(goal, session_id=session_id)
    owner = perm["owner_session_id"]
    cur = perm["current_session_id"]
    if not owner:
        owned_by = "unclaimed"
    elif not cur:
        owned_by = "unknown"
    elif owner == cur:
        owned_by = "self"
    else:
        owned_by = "other"
    return {
        "goal_owner_session_id": owner,
        "owned_by": owned_by,
        "claimed_by_other": owned_by == "other",
    }


def read_side_banner(goal: dict | None, *, session_id: str | None = None) -> str:
    """get_goal 恢复横幅（仅归属/接管提示，无写动作）。"""
    if goal is None:
        return ""
    fields = ownership_fields(goal, session_id=session_id)
    owner = fields["goal_owner_session_id"]
    if fields["owned_by"] == "self":
        return f"归属: 本会话（owner_session_id={mask_session(owner)}）"
    if fields["owned_by"] == "other":
        return (
            f"⚠ 归属: 其他会话（owner_session_id={mask_session(owner)}）——跨会话写将被拒绝"
            "（reason_code=cross_session_write_denied）；确需写入走 cross_session=true "
            "+ reason + evidence_refs 显式授权"
        )
    if fields["owned_by"] == "unclaimed":
        return "归属: 未认领（无 owner，legacy/新建未绑定；写入按 owner_unknown 标注）"
    return f"归属: 本会话身份不可证明（owner_session_id={mask_session(owner)}，session_unverified）"


# ---------------------------------------------------------------------------
# L2: coordination_status 数据面（DESIGN-20261101 §4.4）
# ---------------------------------------------------------------------------


def _parse_ts(raw: str):
    from datetime import datetime

    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _coordination_goal_entry(
    g: dict,
    task_store,
    *,
    sid: str,
    now,
    window_hours: int,
    only_in_flight: bool,
) -> tuple[dict | None, list[str]]:
    """单个 goal 的协调条目；返回 (entry|None, degraded_notes)。None=被窗口过滤掉。"""
    gid = str(g.get("id") or "")
    if not gid:
        return None, []
    status = str(g.get("status") or "")
    updated = _parse_ts(g.get("updated_at", ""))
    if (
        window_hours
        and updated is not None
        and (now - updated).total_seconds() > int(window_hours) * 3600
    ):
        return None, []
    if only_in_flight and status != "active":
        return None, []

    notes: list[str] = []
    counts = {
        "tasks_total": 0,
        "ready": 0,
        "in_progress": 0,
        "blocked": 0,
        "waiting_cross_goal": 0,
        "done": 0,
    }
    doing_title = ""
    try:
        fr = task_store.compute_frontier(gid)
        counts.update(
            {
                "tasks_total": int(fr.get("total", 0)),
                "ready": len(fr.get("ready", [])),
                "in_progress": len(fr.get("in_progress", [])),
                "blocked": len(fr.get("blocked", [])),
                "waiting_cross_goal": len(fr.get("waiting_cross_goal", [])),
                "done": len(fr.get("completed", [])),
            }
        )
        for note in fr.get("cross_goal_degraded", []) or []:
            notes.append(str(note))
        for e in fr.get("in_progress", []) or []:
            task = e.get("task")
            if task is not None and not doing_title:
                doing_title = str(getattr(task, "title", "") or "")
    except Exception as exc:  # noqa: BLE001 — 单 goal 任务账损坏不拖垮整体视图
        notes.append(f"任务账不可读: {exc}")

    cps = g.get("checkpoints") or []
    last_cp = cps[-1] if cps else {}
    perm = resolve_write_permission(g, session_id=sid)
    if perm["current_session_id"] and perm["owner_session_id"] == perm["current_session_id"]:
        owned_by = "self"
    elif perm["owner_session_id"]:
        owned_by = "other"
    else:
        owned_by = "unclaimed"
    entry = {
        "goal_id": gid,
        "title": str(g.get("objective") or "")[:60],
        "status": status,
        "owned_by": owned_by,
        "owner_session_id": perm["owner_session_id"],
        "owner_masked": perm["owner_masked"],
        "created_at": str(g.get("created_at") or ""),
        "updated_at": str(g.get("updated_at") or ""),
        "version": int(g.get("version") or 1),
        "last_checkpoint": {
            "ts": str((last_cp or {}).get("ts") or ""),
            "what": str((last_cp or {}).get("what") or "")[:80],
        },
        "open_tasks": (
            counts["ready"]
            + counts["in_progress"]
            + counts["blocked"]
            + counts["waiting_cross_goal"]
        ),
        "task_counts": counts,
        "next": doing_title[:80],
        "degraded": notes,
    }
    return entry, notes


def _degraded_goal_entry(g: dict, *, err: str) -> tuple[dict, list[str]]:
    """单条 goal 记录不可解析时的降级条目：形状与正常条目一致，字段值不伪造结论."""
    rec = g if isinstance(g, dict) else {}
    note = f"goal 记录不可解析: {err}"
    entry = {
        "goal_id": str(rec.get("id") or "?"),
        "title": str(rec.get("objective") or "")[:60],
        "status": str(rec.get("status") or ""),
        "owned_by": "unknown",
        "owner_session_id": "",
        "owner_masked": "",
        "created_at": str(rec.get("created_at") or ""),
        "updated_at": str(rec.get("updated_at") or ""),
        "version": 0,
        "last_checkpoint": {"ts": "", "what": ""},
        "open_tasks": 0,
        "task_counts": {
            "tasks_total": 0,
            "ready": 0,
            "in_progress": 0,
            "blocked": 0,
            "waiting_cross_goal": 0,
            "done": 0,
        },
        "next": "",
        "degraded": [note],
    }
    return entry, [note]


def _rollup_session(sessions: dict, entry: dict, *, sid: str) -> None:
    """把 goal 条目并入 session 汇总（纯聚合，无写）。"""
    owner = entry["owner_session_id"]
    key = owner or "<unclaimed>"
    bucket = sessions.setdefault(
        key,
        {
            "session_id": owner,
            "is_self": bool(sid and key == sid),
            "goals": [],
            "open_tasks": 0,
            "blocked_tasks": 0,
            "last_activity_at": "",
        },
    )
    bucket["goals"].append(entry["goal_id"])
    bucket["open_tasks"] += int(entry["open_tasks"])
    bucket["blocked_tasks"] += int((entry["task_counts"] or {}).get("blocked") or 0)
    ts = str(entry.get("updated_at") or "")
    if ts > bucket["last_activity_at"]:
        bucket["last_activity_at"] = ts


def coordination_snapshot(
    audit_dir: str,
    *,
    window_hours: int = 24,
    only_in_flight: bool = True,
    session_id: str | None = None,
) -> dict:
    """goal/任务维度的只读协调快照（不做写、不做裁决）。

    数据面边界（诚实登记）: goals/tasks/owner/last_checkpoint 来自真实账本；
    running.children / running.jobs / recent_events 本层未接线 → 显式进 degraded，
    不返回伪造空值冒充「无运行」（字段形状按 §4.4 固定，接线后原地替换）。
    """
    from llm_loop.timekeeping import system_local_now

    sid = authority_session_id() if session_id is None else str(session_id or "")
    now = system_local_now()
    degraded: list[str] = []
    goals_out: list[dict] = []
    sessions: dict[str, dict] = {}
    try:
        from llm_loop.introspection.goal import GoalStore

        goals = GoalStore(str(audit_dir)).list(limit=200)
    except Exception as exc:  # noqa: BLE001 — 账本不可读 → degraded 而非伪造空视图
        return {
            "ok": False,
            "generated_at": now.isoformat(),
            "window_hours": int(window_hours),
            "only_in_flight": bool(only_in_flight),
            "goals": [],
            "sessions": [],
            "running": {"children": [], "jobs": []},
            "recent_events": [],
            "degraded": [f"goal 账本不可读: {exc}"],
        }

    from llm_loop.introspection.task_store import TaskStore

    task_store = TaskStore(str(audit_dir))
    for g in goals:
        try:
            entry, notes = _coordination_goal_entry(
                g,
                task_store,
                sid=sid,
                now=now,
                window_hours=window_hours,
                only_in_flight=only_in_flight,
            )
        except Exception as exc:  # noqa: BLE001 — 单条记录不可解析不拖垮整视图（P1-2）
            entry, notes = _degraded_goal_entry(g, err=str(exc))
        if entry is None:
            continue
        goals_out.append(entry)
        for note in notes:
            degraded.append(f"{entry['goal_id']}: {note}")
        _rollup_session(sessions, entry, sid=sid)

    degraded.extend(
        [
            "running.children: 未接线（本层未采集子代理租约）",
            "running.jobs: 未接线（本层未采集调度/后台任务）",
            "recent_events: 未接线（本层未查询事件流）",
        ]
    )
    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "window_hours": int(window_hours),
        "only_in_flight": bool(only_in_flight),
        "self_session": mask_session(sid),
        "goals": goals_out,
        "sessions": list(sessions.values()),
        "running": {"children": [], "jobs": []},
        "recent_events": [],
        "degraded": degraded,
    }


def render_coordination(snapshot: dict) -> str:
    """把快照渲染成模型可读文本（Decision Packet 友好）。"""
    lines: list[str] = [
        f"[coordination_status] ok={snapshot.get('ok')} "
        f"window={snapshot.get('window_hours')}h goals={len(snapshot.get('goals') or [])} "
        f"self={snapshot.get('self_session') or '<无 binding>'}"
    ]
    for g in snapshot.get("goals") or []:
        tc = g.get("task_counts") or {}
        lines.append(
            f"  {g['goal_id']} [{g['status']}] {g['title'][:40]} | owner={g['owned_by']}"
            f"({g['owner_masked'] or '-'}) ver={g['version']} | tasks open={g['open_tasks']}"
            f" ready={tc.get('ready')} doing={tc.get('in_progress')} blocked={tc.get('blocked')}"
            f" xwait={tc.get('waiting_cross_goal')}"
        )
        cp = g.get("last_checkpoint") or {}
        if cp.get("what"):
            lines.append(f"      last_cp {cp.get('ts','')} {cp.get('what','')}")
        for note in g.get("degraded") or []:
            lines.append(f"      ⚠ {note}")
    for s in snapshot.get("sessions") or []:
        lines.append(
            f"  session {mask_session(s.get('session_id') or '') or '<unclaimed>'} "
            f"self={s.get('is_self')} goals={len(s.get('goals') or [])} "
            f"open={s.get('open_tasks')} blocked={s.get('blocked_tasks')}"
            f" last={s.get('last_activity_at') or '-'}"
        )
    for note in snapshot.get("degraded") or []:
        lines.append(f"  ⚠ degraded: {note}")
    return "\n".join(lines)
