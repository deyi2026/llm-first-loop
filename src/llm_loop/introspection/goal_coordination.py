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

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DENY_REASON = "cross_session_write_denied"
REASON_OWNER_UNKNOWN = "owner_unknown"
REASON_CROSS_AUTHORIZED = "cross_session_authorized"
REASON_SESSION_UNVERIFIED = "session_unverified"

DECISION_ALLOW = "allow"
DECISION_ALLOW_ANNOTATED = "allow_annotated"
DECISION_DENY = "deny"

#: 协调视图单次最多呈现的 goal 条数（D5 裁决）。
#: 200 的旧值在本仓库已实测漏数：账本 239 行时最旧 39 条不进视图，其中 12 个
#: 是 active goal（可见 78/90）。500 覆盖当前量级 2 倍余量，超限由
#: ``capacity.truncated`` + degraded ``goals_truncated`` 自证，不静默丢。
_GOALS_VIEW_LIMIT = 500

#: running 段单次呈现上限（DESIGN-20261103 Q15：默认 top-N + 其余只计数）。
#: 截断必须由 ``*_truncated`` + degraded 自证，不静默丢在跑的活。
_RUNNING_TOP_N = 10

#: recent_events 段（T-0.4b）呈现上限与窗口（DESIGN-20261103 §6.4）.
#: 窗口用**时间**而非字节定义：本仓库实测 128KB 的 action_trace 只覆盖
#: 3 分 11 秒，字节窗口的「最近」会被突发流量压缩成不可解释的量。
_EVENTS_TOP_N = 10
_EVENTS_WINDOW_S = 1800
#: 单流尾部读取硬上限：实测 2MB 解析 ≈ 9ms（action_trace 5080 行），
#: 与 80ms 视图预算相比有量级余量；超过上限即为截断，必须自证。
_EVENTS_MAX_BYTES = 2 * 1024 * 1024

#: 参与 recent_events 的审计流子集（名, 文件名, 摘要键）——故意只取两条：
#: ``action_trace`` 是「谁在动」的活动主干，``exception_log`` 是「谁在坏」；
#: ``declaration_check``（317MB，非活动信号）等其余流不进默认窗口。
#: 摘要键避开 ``phase``（如 ``action.tool_loop``）这类分组噪声，只留「做了什么」。
#: 文件名与 ``introspection.search.RecordSearcher._EVENT_STREAMS`` 必须一致，
#: 由单测 ``test_stream_map_matches_search_registry`` 防漂移。
_RECENT_EVENT_STREAMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("action_trace", "action_trace.jsonl", ("action_type", "detail")),
    ("exception_log", "exception_log.jsonl", ("error_type", "detail")),
)


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
            '  2) 显式跨会话写入：同一调用加 cross_session=true + reason="<为什么必须由你写>"'
            ' + evidence_refs=["evidence://..."]\n'
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
        f'  1) 只读查看：get_goal(goal_id="{gid}") / task_frontier(goal_id="{gid}")'
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
            "（reason_code=cross_session_write_denied）；仅 goal 记录写入（checkpoint_goal/"
            "update_goal）可走 cross_session=true + reason + evidence_refs 显式授权；"
            "推进该 goal 的任务图（task_create/task_update）无跨会话出口，须由 owner 会话执行"
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


def _ts_key(raw: str):
    """把 ISO 时间戳转成可跨记录比较的 aware datetime；空/非法 → None.

    为什么不能直接比字符串: 账本里同时存在 `+08:00` 与 `+00:00` 两种时区写法
    （2026-11-03 实测），字符串序与时序不一致，必须按绝对时刻比。
    """

    dt = _parse_ts(raw)
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


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
    # 先按 in-flight 剪枝（非 active goal 不必付 frontier 成本）；窗口判断必须挪到
    # frontier 之后——窗口口径是 activity_at（N1-A8），需要 task 侧最近写入时间。
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
    last_task_activity = ""
    try:
        fr = task_store.compute_frontier(gid)
        last_task_activity = str(fr.get("last_activity") or "")
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

    # 窗口口径（N1-A8）: activity_at = max(goal.updated_at, 该 goal 最新 task.updated_at)。
    # 只比 goal.updated_at 会把「goal 久未改、任务仍在推进」误判为陈旧；实测本仓库
    # goal 最新写入已 31.5h 前、90 个 active 在 24h 窗口内为 0 —— 单看 goal 侧会让
    # 视图长期全空（E9）。两侧都读不到时间戳时不过滤（宁可多显示，不可静默吞掉）。
    goal_updated_raw = str(g.get("updated_at") or "")
    goal_dt = _ts_key(goal_updated_raw)
    task_dt = _ts_key(last_task_activity)
    if task_dt is not None and (goal_dt is None or task_dt > goal_dt):
        activity_at, activity_source = last_task_activity, "task"
    elif goal_dt is not None:
        activity_at, activity_source = goal_updated_raw, "goal"
    else:
        activity_at, activity_source = "", "none"
    activity_dt = max((d for d in (goal_dt, task_dt) if d is not None), default=None)
    if window_hours and activity_dt is not None:
        try:
            too_old = (now - activity_dt).total_seconds() > int(window_hours) * 3600
        except TypeError:  # naive/aware 混用 → 不过滤，宁多勿吞
            too_old = False
        if too_old:
            return None, []

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
        "activity_at": activity_at,
        "activity_source": activity_source,
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
        "activity_at": str(rec.get("updated_at") or ""),
        "activity_source": "unknown",
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


def _collect_goal_entries(
    goals: list[dict],
    task_store: Any,
    *,
    sid: str,
    now: Any,
    window_hours: int,
    only_in_flight: bool,
) -> tuple[list[dict], dict[str, dict], list[str]]:
    """逐 goal 组装视图条目；返回 (goals_out, sessions, degraded_notes)。

    单条记录不可解析只降级该条，不拖垮整视图（P1-2）。把它从
    ``coordination_snapshot`` 抽出来的直接原因：留在一个 130 行的函数里，
    函数行数守卫棘轮与可读性都会持续变差（RULE-AI-24 防退化）。
    """
    goals_out: list[dict] = []
    sessions: dict[str, dict] = {}
    notes_out: list[str] = []
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
            notes_out.append(f"{entry['goal_id']}: {note}")
        _rollup_session(sessions, entry, sid=sid)
    return goals_out, sessions, notes_out


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


def _collect_running(*, sid: str, ctx: Any | None) -> tuple[dict, list[str]]:
    """采集 ``running`` 段（N1 接线，DESIGN-20261103 §6.4）.

    事实源都是**进程内内存态**（§10-R4 边界）:
    - child: ``ctx.subagent_runner.all_active_children()``，在飞判据
      ``handle.state == "running"``（Q39(a)：集合成员资格不能当在飞判据）。
    - job: ``ctx.job_registry.active_all()``，在飞判据
      ``not done and not killed``（与 ``active_for_session`` 同源）。

    未装配 → 该子段显式 degraded：「未接线」≠「无运行」。他人 session 的
    child/job 只出脱敏行与计数，不出完整 child_id、命令文本（Q13）。
    """
    from datetime import datetime

    from llm_loop.timekeeping import system_local_now

    degraded: list[str] = []
    running: dict[str, Any] = {
        # children 归属只能挂在 session 上（Q39(b)）：goal→owner_session→children，
        # 无 owner 的 goal 永远没有自己的 child，因此必须回执归属口径。
        "children_scope": "owner_session",
        "children": [],
        "children_mine_total": 0,
        "children_others_total": 0,
        "children_truncated": 0,
        "jobs": [],
        "jobs_mine_total": 0,
        "jobs_others_total": 0,
        "jobs_truncated": 0,
    }

    runner = getattr(ctx, "subagent_runner", None) if ctx is not None else None
    if runner is None:
        degraded.append(
            "running.children: 未装配 subagent_runner（本层无 child 事实源；不代表没有 child 在跑）"
        )
    else:
        try:
            handles = list(runner.all_active_children())
        except Exception as exc:  # noqa: BLE001 — 采集异常如实降级，不伪造空
            degraded.append(f"running.children: 采集失败 {exc}")
            handles = []
        mine: list[dict] = []
        others: list[dict] = []
        for handle in handles:
            parent = str(getattr(handle, "parent_id", "") or "")
            # 视图侧再判一次在飞：事实源若多返（终态未清、窗口竞态），
            # 视图不得把它当在跑——宁可少报，不可伪报在飞。
            if str(getattr(handle, "state", "") or "") != "running":
                continue
            is_mine = bool(sid) and parent == sid
            row = {
                "child_id": str(getattr(handle, "child_id", "") or "") if is_mine else "",
                "parent_masked": mask_session(parent),
                "state": str(getattr(handle, "state", "") or ""),
                # generation 是 parent run 代际（handle 有该字段）；仅供关联，不推断存活。
                "generation": str(getattr(handle, "generation", "") or "") if is_mine else "",
                "depth": int(getattr(handle, "depth", 0) or 0),
                "is_mine": is_mine,
            }
            (mine if is_mine else others).append(row)
        running["children_mine_total"] = len(mine)
        running["children_others_total"] = len(others)
        shown_mine = mine[:_RUNNING_TOP_N]
        shown_others = others[:_RUNNING_TOP_N]
        running["children_truncated"] = (
            len(mine) - len(shown_mine) + (len(others) - len(shown_others))
        )
        if running["children_truncated"]:
            degraded.append(
                f"running.children_truncated: 呈现 {len(shown_mine)}+{len(shown_others)}"
                f" / 共 {len(mine)}+{len(others)}（本会话+他人，其余只计数）"
            )
        running["children"] = shown_mine + shown_others

    job_registry = getattr(ctx, "job_registry", None) if ctx is not None else None
    if job_registry is None:
        degraded.append(
            "running.jobs: 未装配 job_registry（本层无后台执行事实源；不代表没有任务在跑）"
        )
    else:
        try:
            jobs = list(job_registry.active_all())
        except Exception as exc:  # noqa: BLE001
            degraded.append(f"running.jobs: 采集失败 {exc}")
            jobs = []
        mine_jobs: list[dict] = []
        other_jobs = 0
        for job in jobs:
            # 同 children：视图侧再判一次在飞（与 active_for_session 同口径）。
            if bool(getattr(job, "done", False)) or bool(getattr(job, "killed", False)):
                continue
            owner = str(getattr(job, "session_id", "") or "")
            if not (bool(sid) and owner == sid):
                other_jobs += 1
                continue
            started = float(getattr(job, "started_at", 0.0) or 0.0)
            mine_jobs.append(
                {
                    "job_id": str(getattr(job, "id", "") or ""),
                    "command": str(getattr(job, "command", "") or "")[:80],
                    "executor": str(getattr(job, "executor", "") or ""),
                    "started_at": (
                        datetime.fromtimestamp(started).astimezone().isoformat() if started else ""
                    ),
                    "is_mine": True,
                }
            )
        running["jobs_mine_total"] = len(mine_jobs)
        running["jobs_others_total"] = other_jobs
        shown_jobs = mine_jobs[:_RUNNING_TOP_N]
        running["jobs_truncated"] = len(mine_jobs) - len(shown_jobs)
        if running["jobs_truncated"] or other_jobs:
            degraded.append(
                f"running.jobs_truncated: 呈现 {len(shown_jobs)}/{len(mine_jobs)}"
                f"（本会话），他人 session 另有 {other_jobs} 个在跑（只计数）"
            )
        running["jobs"] = shown_jobs
    # 采集时刻自证：running 是内存态瞬时快照，不保证与 generated_at 严格同刻。
    running["observed_at"] = system_local_now().isoformat()
    return running, degraded


def _entry_ts(entry: dict) -> datetime | None:
    """事件时间戳（与 ``RecordSearcher.event_stream`` 同口径的三个候选键）.

    解析失败/缺失 → None（由调用方计入 unstamped，不猜测时间）。无时区的值按
    本机时区解释：审计流写入方都用 ``system_local_now()``，即带偏移的本地时间。
    """
    for key in ("ts", "created_at", "timestamp"):
        val = entry.get(key)
        if not isinstance(val, str) or not val.strip():
            continue
        try:
            parsed = datetime.fromisoformat(val.strip())
        except ValueError:
            continue
        return parsed if parsed.tzinfo is not None else parsed.astimezone()
    return None


def _scan_stream_tail(
    path: Path, *, cutoff: datetime, max_bytes: int
) -> tuple[list[tuple[datetime, dict]], bool, int, int]:
    """从文件尾部倒着扫到 ``cutoff`` 为止（时间窗口 + 字节上限双界）.

    返回 ``(窗口内[(ts, entry)], 是否抵达 cutoff, 扫描字节, 无时间戳条数)``。

    倒着扫而非正着扫：正扫 375MB 的 action_trace 实测 3029ms，倒扫通常只解析
    尾部数十 KB。「最近」由 cutoff 定义，字节上限只做兜底——触顶即
    ``reached_cutoff=False``，由调用方标注截断，不冒充「窗口内没有更早事件」。
    """
    size = path.stat().st_size
    start = max(0, size - max_bytes)
    with path.open("rb") as f:
        f.seek(start)
        raw = f.read()
    lines = raw.split(b"\n")
    if start > 0:
        # 首行大概率被 start 切断：丢弃，绝不把半条 JSON 当事件。
        lines = lines[1:]
    rows: list[tuple[datetime, dict]] = []
    unstamped = 0
    reached = start == 0
    for raw_line in reversed(lines):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(entry, dict):
            continue
        ts = _entry_ts(entry)
        if ts is None:
            unstamped += 1
            continue
        if ts < cutoff:
            reached = True
            break
        rows.append((ts, entry))
    rows.reverse()  # 旧→新
    return rows, reached, size - start, unstamped


def _human_bytes(size: int) -> str:
    """字节数的人读形式（审计回执用；<1KB 直接给 B，避免出现「0KB」）."""
    return f"{size // 1024}KB" if size >= 1024 else f"{size}B"


def _collect_recent_events(
    audit_dir: str,
    *,
    sid: str,
    now: datetime,
    window_s: int = _EVENTS_WINDOW_S,
    top_n: int = _EVENTS_TOP_N,
) -> tuple[dict, list[str]]:
    """采集 ``recent_events`` 段（T-0.4b，DESIGN-20261103 §6.4）.

    语义边界（诚实登记）:
    - **workspace-wide**：事件来自审计流文件，跨进程/跨会话可见；这一点强于
      ``running``（内存态）。但 ``session_id`` 并非每条都在（历史记录曾恒空），
      缺失行标 ``attributed=false``，不做归属猜测。
    - **窗口是时间的**：``window_s`` 内的事件；字节上限兜底，触顶即
      ``recent_events_truncated=true`` + degraded 自证。
    - 「0 条」只代表**窗口内**没有事件，不代表系统没动过；空视图不在此处
      编造 degraded（N1-A2），只由 ``coverage`` 字段说明覆盖时长。
    """
    degraded: list[str] = []
    block: dict[str, Any] = {
        "recent_events": [],
        "recent_events_total": 0,
        "recent_events_truncated": False,
        "recent_events_window_s": int(window_s),
        "recent_events_coverage_s": None,
        "recent_events_scanned_bytes": 0,
        "recent_events_streams": [name for name, _, _ in _RECENT_EVENT_STREAMS],
        "recent_events_scope": "workspace",
        "recent_events_observed_at": now.isoformat(),
    }
    root = Path(str(audit_dir or ""))
    if not str(audit_dir or "") or not root.is_dir():
        degraded.append("recent_events: audit_dir 不可读（本层无事件源；不代表没有事件发生）")
        return block, degraded

    cutoff = now - timedelta(seconds=int(window_s))
    collected: list[tuple[datetime, dict]] = []
    unstamped_total = 0
    byte_capped: list[str] = []
    for name, fname, keys in _RECENT_EVENT_STREAMS:
        path = root / fname
        if not path.is_file():
            continue
        try:
            rows, reached, scanned, unstamped = _scan_stream_tail(
                path, cutoff=cutoff, max_bytes=_EVENTS_MAX_BYTES
            )
        except OSError as exc:  # noqa: BLE001 — 单流读失败不拖垮整视图
            degraded.append(f"recent_events.{name}: 读取失败 {exc}")
            continue
        block["recent_events_scanned_bytes"] += scanned
        unstamped_total += unstamped
        if not reached:
            byte_capped.append(name)
        for ts, entry in rows:
            raw_sid = str(entry.get("session_id") or "")
            collected.append(
                (
                    ts,
                    {
                        "stream": name,
                        "ts": ts.isoformat(),
                        "session_id": mask_session(raw_sid),
                        "is_mine": bool(sid) and raw_sid == sid,
                        "attributed": bool(raw_sid),
                        "summary": " ".join(str(entry.get(k, "")) for k in keys)[:200],
                    },
                )
            )

    total = len(collected)
    block["recent_events_total"] = total
    if total:
        collected.sort(key=lambda pair: pair[0])
        oldest = collected[0][0]
        block["recent_events_coverage_s"] = max(0.0, (now - oldest).total_seconds())
        shown = collected[-top_n:]  # 取最近 top_n，保持旧→新
        block["recent_events"] = [item for _, item in shown]
    over_limit = total > top_n
    block["recent_events_truncated"] = bool(over_limit or byte_capped)
    if over_limit:
        degraded.append(
            f"recent_events_truncated: 呈现最近 {top_n}/{total} 条"
            f"（窗口 {int(window_s)}s 内命中更多，只出 top-N）"
        )
    if byte_capped:
        degraded.append(
            f"recent_events_truncated: {'/'.join(byte_capped)} 尾部"
            f" {_human_bytes(_EVENTS_MAX_BYTES)} 内未回溯到 {int(window_s)}s 前"
            "（实际覆盖不足整窗，coverage_s 为真实跨度）"
        )
    if unstamped_total:
        degraded.append(
            f"recent_events: {unstamped_total} 条记录无可用时间戳（未计入窗口，不猜时间）"
        )
    return block, degraded


def _collect_claim_metrics(audit_dir: str) -> tuple[dict, list[str]]:
    """claim/fanout 事件流的健康度（T-0.6，DESIGN-20261103 §6.6）。

    只报两件机械事实：事件流规模（行/坏行/字节）与本进程 append 失败数。
    ``write_failures > 0`` 意味着分母残缺 —— 此时任何比率都不得直接对外报数
    （不变量 3）。坏行（崩溃留下的半行）不报 degraded：那是预期现象，不是损坏。
    """
    from llm_loop.introspection.claims.events import read_events_stats, write_failures

    stats = read_events_stats(audit_dir)
    failures = write_failures(audit_dir)
    block: dict[str, Any] = {
        "claims_events": stats,
        "claim_event_write_failures": failures,
    }
    notes: list[str] = []
    if failures:
        notes.append(
            f"claim_metrics: 本进程事件写入失败 {failures} 次（分母不完整，比率不得直接对外报数）"
        )
    if stats.get("note") == "skipped_scan_over_cap":
        notes.append(
            f"claim_events_large: 事件流 {stats.get('bytes')}B 超过扫描上限（只回 size，未计行数）"
        )
    return block, notes


# ---------------- 合并队列失败分诊（R5：只读，零写） ----------------

#: failure_class(6) → 四类可行动桶(4)。未知/空一律归 human（fail-closed，不漏项）。
_QUEUE_BUCKETS = {
    "env_transient": "retry",
    "needs_rebase": "rebase",
    "verify_missing": "verify",
    "env_config": "human",
    "true_conflict": "human",
    "needs_serialize": "human",
}
_QUEUE_BUCKET_LABELS = {
    "retry": "该重投",
    "rebase": "该 rebase",
    "verify": "该补凭证",
    "human": "该人看",
}


#: lane 终态：已合并/已关闭/已放弃。对这些 lane 再 requeue/rebase 必然失败。
_TERMINAL_LANE_STATUSES = frozenset({"merged", "closed", "abandoned"})


def _lane_status_map(audit_dir: str) -> dict[str, str]:
    """只读 lanes.jsonl → {lane_id: status}（同 id 取最后一行，即最新状态）。

    读失败返回空 dict：分诊退化为「不带 lane 上下文」，仍然逐项给出明细，
    不因旁证缺失丢掉主结果（R5-a 只要求零写，不要求读全）。
    """
    path = Path(audit_dir) / "lanes.jsonl"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("lane_id"):
                    out[str(row["lane_id"])] = str(row.get("status") or "")
    except OSError:
        return {}
    return out


def _queue_next_command(entry: dict, diag: dict, lane_status: str = "") -> str:
    """给每条失败项一条可直接粘贴的下一步命令（R5-c：不是“请排查”这种空话）。

    关键约束：lane 已终态时**不**给可执行命令。对已 merged 的 lane 执行
    requeue/rebase 是必然失败的动作，给出它比不给更糟——R5-c 的「可直接粘贴」
    不等于「随便给一条能粘的」。此时给出的是无需动作的历史项说明。
    """
    lid = str(entry.get("lane_id") or "")
    qid = str(entry.get("queue_id") or "")
    if not lid:
        return f"# 队列项 {qid} 缺 lane_id，人工核对 merge_queue.jsonl"
    if lane_status in _TERMINAL_LANE_STATUSES:
        return (
            f"# 历史项：lane {lid} 已 {lane_status}，无需动作"
            f"（queue={qid}；账本清理另行判定）"
        )
    cls = str(diag.get("failure_class") or "")
    if cls == "env_transient":
        return f'lane_queue_submit(lane_id="{lid}")  # 环境类，修好后重投'
    if cls == "needs_rebase":
        return f"git -C <lane-worktree> rebase origin/main && lane_queue_submit(lane_id=\"{lid}\")"
    if cls == "verify_missing":
        return f'lane_merge_request(lane_id="{lid}")  # 补/重签凭证后再排队'
    return f"# 需人工判定：{diag.get('primary_reason') or 'unknown'}（queue={qid}）"


def _collect_merge_queue(
    audit_dir: str, *, limit_per_bucket: int = 3
) -> tuple[dict, list[str]]:
    """把 merge_queue.jsonl 的 failed 项压成四类计数 + 每类前 N 条（R5）。

    只读：本函数不调用 MergeQueueStore 的任何写方法，不落任何账本。
    不变量（R5-b）：四类计数之和必须等于 failed 总数；不成立时显式降级，不静默丢项。
    """
    from llm_loop.introspection.merge_queue import classify_failure

    path = Path(audit_dir) / "merge_queue.jsonl"
    lane_status = _lane_status_map(audit_dir)
    buckets = {
        key: {"label": _QUEUE_BUCKET_LABELS[key], "count": 0, "items": []}
        for key in _QUEUE_BUCKET_LABELS
    }
    if not path.exists():
        return (
            {"merge_queue": {"available": False, "failed_total": 0, "buckets": buckets}},
            ["merge_queue: 账本不存在"],
        )

    failed_total = 0
    terminal_total = 0
    malformed = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(entry, dict) or str(entry.get("status")) != "failed":
                    continue
                failed_total += 1
                try:
                    diag = classify_failure(entry)
                except Exception:  # 分诊本身出错不能拖垮整个协调视图
                    diag = {"failure_class": "", "primary_reason": "classify_error"}
                bucket = _QUEUE_BUCKETS.get(str(diag.get("failure_class") or ""), "human")
                buckets[bucket]["count"] += 1
                lane_state = lane_status.get(str(entry.get("lane_id") or ""), "")
                is_terminal = lane_state in _TERMINAL_LANE_STATUSES
                if is_terminal:
                    terminal_total += 1
                if len(buckets[bucket]["items"]) < limit_per_bucket:
                    buckets[bucket]["items"].append(
                        {
                            "queue_id": entry.get("queue_id"),
                            "lane_id": entry.get("lane_id"),
                            "failure_class": str(diag.get("failure_class") or "") or "unknown",
                            "primary_reason": str(diag.get("primary_reason") or ""),
                            "evidence_hint": str(diag.get("evidence_hint") or ""),
                            "lane_status": lane_state,
                            "terminal": is_terminal,
                            "next_command": _queue_next_command(entry, diag, lane_state),
                        }
                    )
    except OSError as exc:
        return (
            {"merge_queue": {"available": False, "failed_total": 0, "buckets": buckets}},
            [f"merge_queue 不可读: {exc}"],
        )

    notes: list[str] = []
    if malformed:
        notes.append(f"merge_queue 有 {malformed} 行不可解析（未计入分诊）")
    summed = sum(int(b["count"]) for b in buckets.values())
    closure_ok = summed == failed_total
    if not closure_ok:  # R5-b：实现错误必须自证，不允许把项丢掉
        notes.append(f"merge_queue 分诊不闭合: 四类合计 {summed} != failed {failed_total}")

    return (
        {
            "merge_queue": {
                "available": True,
                "failed_total": failed_total,
                "buckets": buckets,
                "bucket_sum": summed,
                "closure_ok": closure_ok,
                "malformed_lines": malformed,
                "terminal_total": terminal_total,
            }
        },
        notes,
    )


def coordination_snapshot(
    audit_dir: str,
    *,
    window_hours: int = 24,
    only_in_flight: bool = True,
    session_id: str | None = None,
    ctx: Any | None = None,
) -> dict:
    """goal/任务维度的只读协调快照（不做写、不做裁决）。

    数据面边界（诚实登记，四段口径不同）: goals/tasks/owner/last_checkpoint
    来自真实账本（跨进程可见）；running 段是**进程内内存态**（未装配 → 显式
    degraded，跨进程/重启后不可见）；recent_events 段读审计流（workspace-wide，
    时间窗口 + 字节上限双界，任一触顶标 truncated）；claims_events 段只报
    「埋点自身健康度」（事件行数/坏行/本进程 append 失败数），**不是** claim
    决策指标——PR-0 还没有 claim 层。四段都不做跨进程补全，也不互相冒充：
    账本里没有的活，running 补不了，事件流补不了。
    """
    from llm_loop.timekeeping import system_local_now

    sid = authority_session_id() if session_id is None else str(session_id or "")
    now = system_local_now()
    degraded: list[str] = []
    running, running_notes = _collect_running(sid=sid, ctx=ctx)
    degraded.extend(running_notes)
    events_block, events_notes = _collect_recent_events(audit_dir, sid=sid, now=now)
    degraded.extend(events_notes)
    claims_block, claims_notes = _collect_claim_metrics(audit_dir)
    degraded.extend(claims_notes)
    # R5：队列失败分诊（只读；四类计数闭合性由 closure_ok 自证）
    queue_block, queue_notes = _collect_merge_queue(audit_dir)
    degraded.extend(queue_notes)
    capacity: dict = {
        "goals_limit": _GOALS_VIEW_LIMIT,
        "goals_in_ledger": 0,
        "goals_shown": 0,
        "truncated": False,
    }
    goal_store = None
    total_goals = 0
    try:
        from llm_loop.introspection.goal import GoalStore

        goal_store = GoalStore(str(audit_dir))
        # count() 与 list() 同口径（空行/坏行不计），否则 truncated 的分母不可信。
        total_goals = goal_store.count()
        goals = goal_store.list(limit=_GOALS_VIEW_LIMIT)
        capacity.update(
            goals_in_ledger=total_goals,
            goals_shown=len(goals),
            truncated=total_goals > len(goals),
        )
        if capacity["truncated"]:
            # 截断必须自证：不标注=静默丢 goal。旧值 200 在本仓库实测丢了 12 个
            # active goal（239 行账本，可见 78/90）。
            degraded.append(
                f"goals_truncated: {len(goals)}/{total_goals}"
                f"（只呈现账本最近 {len(goals)} 条；更早的"
                f" {total_goals - len(goals)} 条未进入窗口）"
            )
    except Exception as exc:  # noqa: BLE001 — 账本不可读 → degraded 而非伪造空视图
        return {
            "ok": False,
            "generated_at": now.isoformat(),
            "window_hours": int(window_hours),
            "only_in_flight": bool(only_in_flight),
            "capacity": capacity,
            "goals": [],
            "sessions": [],
            "running": running,
            **events_block,
            **claims_block,
            **queue_block,
            # running/events/queue 都是真实采到的事实，账本失败不连坐它们。
            "degraded": running_notes
            + events_notes
            + claims_notes
            + queue_notes
            + [f"goal 账本不可读: {exc}"],
        }

    from llm_loop.introspection.task_store import TaskStore

    task_store = TaskStore(str(audit_dir))
    goals_out, sessions, goal_notes = _collect_goal_entries(
        goals,
        task_store,
        sid=sid,
        now=now,
        window_hours=window_hours,
        only_in_flight=only_in_flight,
    )
    degraded.extend(goal_notes)

    if not goals_out:
        # 空视图必须自证（E9）：区分「真没有」与「被窗口滤掉」——见 _window_empty_note
        _note = _window_empty_note(goal_store, total_goals, window_hours)
        if _note:
            degraded.append(_note)

    # EVO-20261106-b0806c32: 跨会话 EVO 完成待登记聚合可见（不静默失败）。
    evolution_handoffs = _pending_evolution_handoffs(audit_dir)

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "window_hours": int(window_hours),
        "only_in_flight": bool(only_in_flight),
        "capacity": capacity,
        "self_session": mask_session(sid),
        "goals": goals_out,
        "sessions": list(sessions.values()),
        "running": running,
        **events_block,
        **claims_block,
        **queue_block,
        "evolution_completion_handoffs": evolution_handoffs,
        "degraded": degraded,
    }


def _render_merge_queue(lines: list[str], mq: dict) -> None:
    """渲染 R5 队列分诊段（只读投影；空 dict 不输出任何行）。

    抽成独立函数的直接原因：内联在 ``render_coordination`` 里会让后者越过
    120 行函数守卫阈值（RULE-AI-24 防退化）。
    """
    if not mq:
        return
    if not mq.get("available"):
        lines.append("  队列分诊 merge_queue=<不可用>")
        return
    bt = mq.get("buckets") or {}
    parts = [
        f"{(bt.get(k) or {}).get('label') or k}={(bt.get(k) or {}).get('count', 0)}"
        for k in ("retry", "rebase", "verify", "human")
    ]
    lines.append(
        f"  队列分诊 failed={mq.get('failed_total')} "
        f"闭合={'ok' if mq.get('closure_ok') else 'BROKEN'}({mq.get('bucket_sum')}) "
        f"历史={mq.get('terminal_total', 0)} "
        + " ".join(parts)
    )
    for key in ("retry", "rebase", "verify", "human"):
        for it in (bt.get(key) or {}).get("items") or []:
            lines.append(
                f"      [{key}] {it.get('lane_id') or '-'} "
                f"{it.get('primary_reason') or '-'} → {it.get('next_command') or '-'}"
            )


def render_coordination(snapshot: dict) -> str:
    """把快照渲染成模型可读文本（Decision Packet 友好）。"""
    cap = snapshot.get("capacity") or {}
    limit = cap.get("goals_limit")
    capacity_txt = (
        f"capacity={cap.get('goals_shown')}/{limit}" + ("!" if cap.get("truncated") else "")
        if limit
        else "capacity=?"
    )
    window_txt = (
        f"window={snapshot.get('window_hours')}h"
        if snapshot.get("window_hours")
        else "window=all"
    )
    lines: list[str] = [
        f"[coordination_status] ok={snapshot.get('ok')} "
        f"{window_txt} goals={len(snapshot.get('goals') or [])} "
        f"{capacity_txt} "
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
    handoffs = snapshot.get("evolution_completion_handoffs") or []
    if handoffs:
        # EVO-20261106-b0806c32: 待登记条目聚合可见——owner 会话看到即可一键落账
        ids = ", ".join(str(h.get("suggestion_id")) for h in handoffs[:5])
        lines.append(
            f"  ⏳ evolution 完成待登记 ×{len(handoffs)}（owner 会话重调 evolution_complete"
            f" 自动取用暂存参数）: {ids}"
            + (" 等" if len(handoffs) > 5 else "")
        )
    running = snapshot.get("running") or {}
    if running:
        # 归属口径必须出现在回执里：children 只按 owner session 归属（Q39(b)）。
        lines.append(
            f"  running children_scope={running.get('children_scope') or '?'} "
            f"children={len(running.get('children') or [])}"
            f"({running.get('children_mine_total', 0)} mine"
            f"+{running.get('children_others_total', 0)} others) "
            f"jobs={len(running.get('jobs') or [])}"
            f"({running.get('jobs_mine_total', 0)} mine"
            f"+{running.get('jobs_others_total', 0)} others) "
            f"observed={running.get('observed_at') or '-'}"
        )
        for c in running.get("children") or []:
            who = c.get("child_id") or "<other-parent>"
            lines.append(
                f"    child {who} state={c.get('state')} depth={c.get('depth')} "
                f"parent={c.get('parent_masked') or '-'} mine={c.get('is_mine')}"
            )
        for j in running.get("jobs") or []:
            lines.append(
                f"    job {j.get('job_id')} exec={j.get('executor') or '-'} "
                f"started={j.get('started_at') or '-'} cmd={j.get('command') or ''}"
            )
    if "recent_events_total" in snapshot:
        # 覆盖时长必须出现在回执里：窗口按时间定义，字节上限兜底后真实覆盖可能
        # 短于整窗（hot session 下 128KB 只值 3 分钟），不标注=读者以为看满 30 分钟。
        events = snapshot.get("recent_events") or []
        covered = snapshot.get("recent_events_coverage_s")
        lines.append(
            f"  events {len(events)}/{snapshot.get('recent_events_total') or 0}"
            f"{'!' if snapshot.get('recent_events_truncated') else ''}"
            f" window={snapshot.get('recent_events_window_s')}s"
            f" covered={int(covered) if covered is not None else '-'}s"
            f" streams={','.join(snapshot.get('recent_events_streams') or [])}"
            f" scope={snapshot.get('recent_events_scope') or '?'}"
        )
        for e in events[-5:]:
            who = "[me]" if e.get("is_mine") else (e.get("session_id") or "<no-sid>")
            lines.append(
                f"    {e.get('ts', '')} {e.get('stream', '')} {who} {(e.get('summary') or '')[:80]}"
            )
    if "claims_events" in snapshot:
        # 分母残缺必须看得见：write_failures>0 时比率不能直接报数（§6.6 不变量 3）。
        ce = snapshot.get("claims_events") or {}
        fails = snapshot.get("claim_event_write_failures") or 0
        line_count = ce.get("lines")
        lines.append(
            f"  claims events={'-' if line_count is None else line_count}"
            f" bad={ce.get('bad_lines', 0)} bytes={ce.get('bytes', 0)}"
            f" write_failures={fails}"
        )
    _render_merge_queue(lines, snapshot.get("merge_queue") or {})
    for note in snapshot.get("degraded") or []:
        lines.append(f"  ⚠ degraded: {note}")
    return "\n".join(lines)


def _pending_evolution_handoffs(audit_dir: str | Path) -> list[dict]:
    """跨会话 EVO 完成待登记条目（EVO-20261106-b0806c32 聚合可见）.

    fail-open：handoff 视图失败不连坐 coordination 主视图。
    """
    try:
        from llm_loop.introspection.evolution_handoff import list_pending_handoffs

        return list_pending_handoffs(audit_dir)
    except Exception:  # noqa: BLE001 — handoff 视图失败不连坐主视图
        return []


def _window_empty_note(goal_store: Any, total_goals: int, window_hours: Any) -> str:
    """空视图自证注记（E9）：区分「真没有」与「被窗口滤掉」（coordination_snapshot 内联抽离）."""
    outside_active = -1
    try:
        all_goals = goal_store.list(limit=max(total_goals, 1)) if goal_store else []
        outside_active = sum(1 for g in all_goals if str(g.get("status") or "") == "active")
    except Exception:  # noqa: BLE001 — 计数失败不影响空视图本身
        outside_active = -1
    if outside_active > 0:
        hint = "（传 window_hours=0 查看全部）" if int(window_hours) else ""
        return (
            f"window_empty: 最近 {int(window_hours)}h 内无活动 goal；"
            f"账本内仍有 {outside_active} 个 active goal 未进入窗口{hint}"
        )
    if outside_active == 0:
        return f"window_empty: 无 active goal（最近 {int(window_hours)}h 内亦无活动）"
    return ""
