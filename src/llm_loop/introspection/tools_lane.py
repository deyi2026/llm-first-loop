"""BranchLane 工具实现（DESIGN-20261105 §4.2 / §11 裁决，2026-11-05）.

4 个工具:
- lane_open: 登记一条 lane（分支 × worktree × goal，裁决强制 1:1）
- lane_update: 按 version CAS 更新可变字段
- lane_close: 终态收敛（merged/closed/abandoned，必须给 reason）
- lane_merge_request: 申请合入 main（无有效凭证一律拒绝，A10）

单一数据源: audit_dir/lanes.jsonl（当前态）+ lane_events.jsonl（只追加历史）。
失败口径: 参数缺失 / 1:1 违约 / CAS 冲突 / 损坏 一律 FAILURE 并带 reason_code，不静默降级。
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any

from llm_loop.core.lane_main_write_guard import STALE_AFTER_S
from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.lane import (
    LaneConstraintError,
    LaneStore,
    LaneStoreCorruptionError,
    LaneVersionConflictError,
)

LANE_OPEN_TOOL_DEF: dict = {
    "name": "lane_open",
    "description": (
        "登记一条可合并分支 lane（main 主线多 lane 并行的唯一入口，DESIGN-20261105 §4.2）。"
        "何时用: 在独立 worktree/分支上开工一个可交付改动、且最终要合回 main 时。"
        "硬约束（裁决）: lane 与 goal 强制 1:1——同一 goal 至多一条在途 main lane；"
        "并行拆分用 lane_role=sub 并复用同一 goal。subagent 的 --detach 隔离 worktree "
        "不登记（私有中间态，由父会话收口）。何时不用: 只读分析、或产出不打算合入 main。"
        "失败对策: branch/worktree/goal 占用冲突会如实返回已占用 lane_id。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "分支名（必填，在途唯一）"},
            "worktree": {"type": "string", "description": "工作树绝对路径（必填，在途唯一）"},
            "goal_id": {"type": "string", "description": "绑定的 goal id（必填，裁决 1:1）"},
            "base_main_sha": {
                "type": "string",
                "description": "分叉点 main sha（可选；缺省从 worktree HEAD 自动探测）",
            },
            "lane_role": {
                "type": "string",
                "enum": ["main", "sub"],
                "description": "main=该 goal 的唯一主 lane（默认）；sub=并行拆分，由 main 汇总",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "本 lane 声明会改的路径（用于重叠检测与受影响验证；强烈建议填）",
            },
            "contract_changes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "对外契约变更点（接口/协议/字段），会广播给其他在途 lane",
            },
            "priority": {"type": "string", "enum": ["normal", "hotfix"], "description": "hotfix 可插队"},
        },
        "required": ["branch", "worktree", "goal_id"],
    },
}

LANE_UPDATE_TOOL_DEF: dict = {
    "name": "lane_update",
    "description": (
        "按 version CAS 更新 lane 可变字段（设计 §4.2 / A9）。何时用: 推进状态、更新 head_sha、"
        "补充 paths/contract_changes、挂验证凭证 verify_ref。何时不用: 终态收敛用 lane_close。"
        "并发语义: expected_version 必须传上次回执的 version；冲突时回执带 current_version，"
        "重新读取后重试即可（在 flock 内检出，冲突不写入）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane_id": {"type": "string", "description": "lane id（lane_open 回执）"},
            "expected_version": {"type": "integer", "description": "上次回执的 version（CAS）"},
            "status": {
                "type": "string",
                "enum": ["open", "active", "verifying", "merging"],
                "description": "在途状态（终态必须走 lane_close）",
            },
            "head_sha": {"type": "string", "description": "当前分支 head"},
            "paths": {"type": "array", "items": {"type": "string"}, "description": "替换声明路径集"},
            "contract_changes": {"type": "array", "items": {"type": "string"}},
            "verify_ref": {"type": "string", "description": "验证凭证引用（evidence:// 或凭证 id）"},
            "priority": {"type": "string", "enum": ["normal", "hotfix"]},
            "base_main_sha": {"type": "string", "description": "rebase 后新的分叉点"},
        },
        "required": ["lane_id", "expected_version"],
    },
}

LANE_CLOSE_TOOL_DEF: dict = {
    "name": "lane_close",
    "description": (
        "把 lane 收敛到终态（merged/closed/abandoned），必须给非空 reason（终态可归因）。"
        "何时用: 合并完成、主动放弃、或转交他人。何时不用: 仍在途（用 lane_update）。"
        "语义: 终态不可逆；重复提交同 status+reason 幂等返回。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane_id": {"type": "string"},
            "expected_version": {"type": "integer"},
            "status": {"type": "string", "enum": ["merged", "closed", "abandoned"]},
            "reason": {"type": "string", "description": "终态原因（必填，可归因）"},
        },
        "required": ["lane_id", "expected_version", "reason"],
    },
}

LANE_MERGE_REQUEST_TOOL_DEF: dict = {
    "name": "lane_merge_request",
    "description": (
        "申请把 lane 合入 main（设计 §4.4 / A10）。何时用: 分支已完成且验证通过。"
        "门禁: 无有效 verify_ref 一律拒绝（reason_code=verify_required）——先写验证凭证再申请。"
        "语义: 只把状态推进到 verifying 并入队，不执行 merge（执行权在合并队列/人）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane_id": {"type": "string"},
            "expected_version": {"type": "integer"},
        },
        "required": ["lane_id", "expected_version"],
    },
}

LANE_REAP_TOOL_DEF: dict = {
    "name": "lane_reap",
    "description": (
        "收尾长期不动的 lane（DESIGN-20261114 §4.3）。"
        "何时用: 发现 lane 卡在非终态（如停在 verifying）数日，需要按可证判据收敛时。"
        "硬约束（裁决）: 三判据必须同时成立才收口——超时 + 注入式 liveness 探针判 dead + 工作树干净；"
        "判死只认探针，「超时」只是筛候选（超时≠死亡）。"
        "liveness 谓词不可用时一律不收口（fail-closed），只输出 liveness_unavailable。"
        "收口状态固定 abandoned。收口不等于清理（D2）：工作树删除是独立的不可逆第二步，"
        "默认不执行，只在回执里给出可粘贴的 git worktree remove 命令；"
        "确需自动删除时必须同时传 remove_worktree=true 与 confirm=true。"
        "何时不用: 只想看谁在途用 coordination_status；带 --force 的清理不在本工具权限内。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dry_run": {"type": "boolean", "description": "只报告不动作（默认 true）"},
            "ttl_hours": {"type": "number", "description": "闲置判据阈值小时数（默认 168）"},
            "limit": {"type": "integer", "description": "本次最多处理候选数（默认 20）"},
            "remove_worktree": {
                "type": "boolean",
                "description": "收口后是否回收工作树目录（不可逆；默认 false，且需 confirm=true）",
            },
            "confirm": {
                "type": "boolean",
                "description": "不可逆动作（删工作树）的显式二次确认（默认 false）",
            },
        },
    },
}

LANE_TOOL_DEFS = [
    LANE_OPEN_TOOL_DEF,
    LANE_REAP_TOOL_DEF,
    LANE_UPDATE_TOOL_DEF,
    LANE_CLOSE_TOOL_DEF,
    LANE_MERGE_REQUEST_TOOL_DEF,
]


def _store(host: Any) -> LaneStore | None:
    audit_dir = str(host.audit_dir) if getattr(host, "audit_dir", None) else ""
    if not audit_dir:
        return None
    try:
        return LaneStore(audit_dir)
    except OSError:
        return None


def _fail(message: str, tool: str, reason_code: str) -> ToolResult:
    return ToolResult(
        ToolResultStatus.FAILURE, f"[{reason_code}] {message}", "", tool
    )


def _require_goal_enabled(host: Any) -> bool:
    """lane_require_goal 开关（默认 false）：由宿主显式注入，不直接读环境。

    与 merge_queue.auto_merge_enabled 同口径：新增直接环境访问会撞
    runtime_env_access_gate 的单向棘轮，也会制造「工具认为开了、宿主认为关」
    两处口径。默认 false 是硬要求——§1 E19 有 6 条已合并的真实 lane 用
    不在账本的 goal_id，硬拒会切断这类合法用法。
    """
    return bool(getattr(host, "lane_require_goal", False))


def _render_precheck_notes(precheck: dict) -> str:
    """把 precheck 结果渲染成回执附加段；无告警时返回空串（零噪声）。"""
    lines: list[str] = []
    overlaps = precheck.get("overlap_warning") or []
    if overlaps:
        detail = "; ".join(
            f"{o.get('lane_id')}({o.get('status')}) 共享 {','.join(o.get('shared_paths') or [])}"
            for o in overlaps[:5]
        )
        lines.append(f"路径重叠告警: {detail}（已登记；开工前确认是否重复开发）")
    if precheck.get("goal_unknown"):
        lines.append(
            f"goal 告警: {precheck.get('goal_id')} 不在 goals.jsonl"
            "（可能是探针或账本已轮转；lane_require_goal=true 时会硬拒）"
        )
    err = precheck.get("error")
    if err:
        lines.append(f"预检不可用: {err}（已按无告警继续登记）")
    return ("\n" + "\n".join(lines)) if lines else ""


def _probe_head(worktree: str) -> str:
    """从工作树探测 HEAD；失败返回空（不阻断登记，但回执提示）。"""
    try:
        proc = subprocess.run(
            ["git", "-C", worktree, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _inflight_note(store: LaneStore, exclude: str = "") -> str:
    """在途 lane 概览（U5：让并发方看见是否有人已改同一片）。摘要失败不得阻断主操作。"""
    try:
        rows = [row for row in store.list() if row.get("lane_id") != exclude]
    except Exception:  # noqa: BLE001 — 概览属附加信息
        return ""
    if not rows:
        return "\n在途 lane: 无（当前唯一）"
    lines = [
        f"{row.get('lane_id')} {row.get('branch')} goal={row.get('goal_id')} "
        f"paths={','.join(row.get('paths') or []) or '-'}"
        for row in rows[:5]
    ]
    return "\n在途 lane（开工前先查重叠，避免重复开发）:\n  " + "\n  ".join(lines)


def run_lane_open(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(host)
    if store is None:
        return _fail("audit_dir 未装配，lane 账本不可用", "lane_open", "store_unavailable")
    branch = str(args.get("branch", "") or "").strip()
    worktree = str(args.get("worktree", "") or "").strip()
    goal_id = str(args.get("goal_id", "") or "").strip()
    missing = [n for n, v in (("branch", branch), ("worktree", worktree), ("goal_id", goal_id)) if not v]
    if missing:
        return _fail(f"缺少必填参数 {missing}", "lane_open", "missing_param")

    base_sha = str(args.get("base_main_sha", "") or "").strip() or _probe_head(worktree)
    owner_sid = ""
    try:
        from llm_loop.introspection.tools_status import bound_session_id

        owner_sid = bound_session_id() or ""
    except Exception:  # noqa: BLE001 — 会话绑定仅用于显示
        owner_sid = ""

    # P4 开门预检（R4）：纯读、只加提示，绝不让它阻断合法登记。
    precheck: dict = {}
    try:
        precheck = store.precheck(
            branch=branch,
            worktree=worktree,
            goal_id=goal_id,
            paths=args.get("paths") or [],
        )
    except Exception as exc:  # noqa: BLE001 — 预检是附加信息，失败降级为提示
        precheck = {"error": f"{type(exc).__name__}: {exc}"}
    if precheck.get("goal_unknown") and _require_goal_enabled(host):
        return _fail(
            f"goal_id 不在 goals.jsonl 且 lane_require_goal=true: {goal_id}",
            "lane_open",
            "goal_not_found",
        )

    try:
        lane = store.create(
            branch=branch,
            worktree=worktree,
            base_main_sha=base_sha,
            goal_id=goal_id,
            owner_session_id=owner_sid,
            lane_role=str(args.get("lane_role", "main") or "main"),
            paths=args.get("paths") or [],
            contract_changes=args.get("contract_changes") or [],
            priority=str(args.get("priority", "normal") or "normal"),
        )
    except LaneConstraintError as exc:
        return _fail(str(exc), "lane_open", "constraint_violation")
    except LaneStoreCorruptionError as exc:
        return _fail(str(exc), "lane_open", "store_corruption")
    except OSError as exc:
        return _fail(f"账本写入失败: {exc}", "lane_open", "io_error")

    base_note = "" if base_sha else "\n注意: base_main_sha 未探测到，合并前必须补（否则无法判断落后度）。"
    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[lane 已登记] lane_id={lane.lane_id} version={lane.version} status={lane.status}\n"
        f"branch={lane.branch} role={lane.lane_role} goal={lane.goal_id}\n"
        f"base_main_sha={lane.base_main_sha or '-'} paths={','.join(lane.paths) or '-'}{base_note}"
        f"{_render_precheck_notes(precheck)}"
        f"{_inflight_note(store, exclude=lane.lane_id)}",
        "",
        "lane_open",
    )


def run_lane_update(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(host)
    if store is None:
        return _fail("audit_dir 未装配，lane 账本不可用", "lane_update", "store_unavailable")
    lane_id = str(args.get("lane_id", "") or "").strip()
    if not lane_id:
        return _fail("缺少必填参数 ['lane_id']", "lane_update", "missing_param")
    raw_expected = args.get("expected_version")
    if raw_expected is None:
        return _fail("expected_version 必须是整数（CAS）", "lane_update", "missing_param")
    try:
        expected = int(raw_expected)
    except (TypeError, ValueError):
        return _fail("expected_version 必须是整数（CAS）", "lane_update", "missing_param")

    fields: dict[str, Any] = {}
    for key in ("status", "head_sha", "paths", "contract_changes", "verify_ref", "priority", "base_main_sha"):
        if key in args and args[key] is not None:
            fields[key] = args[key]
    if not fields:
        return _fail("至少提供一个待更新字段", "lane_update", "missing_param")

    try:
        entry = store.update(lane_id, expected_version=expected, **fields)
    except LaneVersionConflictError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[version_conflict] lane={exc.lane_id} expected={exc.expected} "
            f"current={exc.current}；未写入。重新读取后用 current 重试。",
            "",
            "lane_update",
        )
    except LaneConstraintError as exc:
        return _fail(str(exc), "lane_update", "constraint_violation")
    except LaneStoreCorruptionError as exc:
        return _fail(str(exc), "lane_update", "store_corruption")
    except OSError as exc:
        return _fail(f"账本写入失败: {exc}", "lane_update", "io_error")

    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[lane 已更新] lane_id={entry['lane_id']} version={entry['version']} "
        f"status={entry['status']} head={str(entry.get('head_sha') or '-')[:12]}",
        "",
        "lane_update",
    )


def _close_idle_hours(entry: dict) -> float | None:
    """距 last_activity 的小时数；naive/不可解析返回 None（不据此授权）。"""
    raw = str(entry.get("last_activity") or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    return (datetime.now().astimezone() - ts).total_seconds() / 3600.0


def _close_authorization(store: LaneStore, host: Any, lane_id: str) -> str:
    """非属主 lane_close 的机械授权判据（收口治理③b，2026-11-10）。

    返回空串=放行；非空=拒绝说明。无属主/无会话身份/属主本人不设限；属主
    失配时只认两类**可证事实**：该 lane 的合并队列已 merged，或闲置 ≥ 守卫的
    STALE_AFTER_S（4h）。都不满足则拒绝——堵「任何会话可 close 任何 lane」的
    治理缺口（2026-11-10 复核：close 仅 CAS，无属主判定；2026-11-09 曾靠该缺口
    人工代收口僵尸 lane，属应急通道，不应常开）。读不到判定材料时放行，由
    store.close 的 CAS/终态不可逆约束兜底（拒绝须基于已证事实）。
    """
    try:
        entry = store.get(lane_id)
    except Exception:  # noqa: BLE001 — 判定材料读不到：保持既有语义
        return ""
    if entry is None:
        return ""
    owner = str(entry.get("owner_session_id") or "")
    if not owner:
        return ""
    try:
        from llm_loop.introspection.tools_status import bound_session_id

        caller = str(bound_session_id() or "")
    except Exception:  # noqa: BLE001
        caller = ""
    if not caller or caller == owner:
        return ""
    queue_row = None
    try:
        from llm_loop.introspection.merge_queue import MergeQueueStore

        audit_dir = str(host.audit_dir) if getattr(host, "audit_dir", None) else ""
        if audit_dir:
            queue_row = MergeQueueStore(audit_dir, create=False).get(lane_id)
    except Exception:  # noqa: BLE001 — 队列不可读不构成放行依据，继续看闲置事实
        queue_row = None
    if queue_row is not None and str(queue_row.get("status")) == "merged":
        return ""
    idle = _close_idle_hours(entry)
    if idle is not None and idle * 3600.0 >= STALE_AFTER_S:
        return ""
    return (
        f"lane 属主为其他会话（{owner[:8]}…），且无可证收口事实"
        f"（队列未 merged；闲置 {f'{idle:.1f}h' if idle is not None else '不可判定'}"
        f" < {STALE_AFTER_S / 3600.0:.0f}h）。"
        "请协调属主收口，或等事实成立（队列 merged / 闲置超时）后重试；"
        "reason 需引用事实。"
    )


def run_lane_close(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(host)
    if store is None:
        return _fail("audit_dir 未装配，lane 账本不可用", "lane_close", "store_unavailable")
    lane_id = str(args.get("lane_id", "") or "").strip()
    reason = str(args.get("reason", "") or "").strip()
    if not lane_id:
        return _fail("缺少必填参数 ['lane_id']", "lane_close", "missing_param")
    if not reason:
        return _fail("reason 必填（终态可归因）", "lane_close", "missing_param")
    raw_expected = args.get("expected_version")
    if raw_expected is None:
        return _fail("expected_version 必须是整数（CAS）", "lane_close", "missing_param")
    try:
        expected = int(raw_expected)
    except (TypeError, ValueError):
        return _fail("expected_version 必须是整数（CAS）", "lane_close", "missing_param")

    denial = _close_authorization(store, host, lane_id)
    if denial:
        return _fail(
            f"[close_not_authorized] {denial}",
            "lane_close",
            "close_not_authorized",
        )

    try:
        entry = store.close(
            lane_id,
            expected_version=expected,
            status=str(args.get("status", "closed") or "closed"),
            reason=reason,
        )
    except LaneVersionConflictError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[version_conflict] lane={exc.lane_id} expected={exc.expected} "
            f"current={exc.current}；未写入。重新读取后用 current 重试。",
            "",
            "lane_close",
        )
    except LaneConstraintError as exc:
        return _fail(str(exc), "lane_close", "constraint_violation")
    except LaneStoreCorruptionError as exc:
        return _fail(str(exc), "lane_close", "store_corruption")
    except OSError as exc:
        return _fail(f"账本写入失败: {exc}", "lane_close", "io_error")

    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[lane 已收敛] lane_id={entry['lane_id']} status={entry['status']} "
        f"reason={entry.get('close_reason')} version={entry['version']}",
        "",
        "lane_close",
    )


def run_lane_merge_request(ctx: Any, host: Any, args: dict) -> ToolResult:
    store = _store(host)
    if store is None:
        return _fail("audit_dir 未装配，lane 账本不可用", "lane_merge_request", "store_unavailable")
    lane_id = str(args.get("lane_id", "") or "").strip()
    if not lane_id:
        return _fail("缺少必填参数 ['lane_id']", "lane_merge_request", "missing_param")
    raw_expected = args.get("expected_version")
    if raw_expected is None:
        return _fail("expected_version 必须是整数（CAS）", "lane_merge_request", "missing_param")
    try:
        expected = int(raw_expected)
    except (TypeError, ValueError):
        return _fail("expected_version 必须是整数（CAS）", "lane_merge_request", "missing_param")

    try:
        current = store.get(lane_id)
    except LaneStoreCorruptionError as exc:
        return _fail(str(exc), "lane_merge_request", "store_corruption")
    if current is None:
        return _fail(f"lane 不存在: {lane_id}", "lane_merge_request", "not_found")
    if not str(current.get("verify_ref") or "").strip():
        return _fail(
            "无有效验证凭证（A10：无凭证不合）。先用 lane_update 写 verify_ref 再申请。",
            "lane_merge_request",
            "verify_required",
        )
    try:
        entry = store.request_merge(lane_id, expected_version=expected)
    except LaneVersionConflictError as exc:
        return ToolResult(
            ToolResultStatus.FAILURE,
            f"[version_conflict] lane={exc.lane_id} expected={exc.expected} "
            f"current={exc.current}；未写入。",
            "",
            "lane_merge_request",
        )
    except LaneConstraintError as exc:
        return _fail(str(exc), "lane_merge_request", "constraint_violation")
    except OSError as exc:
        return _fail(f"账本写入失败: {exc}", "lane_merge_request", "io_error")

    return ToolResult(
        ToolResultStatus.SUCCESS,
        f"[已申请合并] lane_id={entry['lane_id']} status={entry['status']} version={entry['version']} "
        f"verify_ref={entry.get('verify_ref')}\n"
        "说明: lane 已转入 merging 态；尚未进入合并队列"
        "（需另行 lane_queue_submit 才会入队），也未执行任何 merge。",
        "",
        "lane_merge_request",
    )


# ---------------- lane 生命周期收尾（P2，DESIGN-20261114 §4.3） ----------------


def _probe_tree_state(worktree: str) -> str:
    """工作树状态：clean / dirty / unknown。只读，不动工作树。"""
    try:
        proc = subprocess.run(
            ["git", "-C", worktree, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return "clean" if not (proc.stdout or "").strip() else "dirty"


def _liveness_probe(host: Any):
    """取宿主注入的 liveness 探针；未注入 → None（不可用 → 一律不收口）。"""
    probe = getattr(host, "lane_liveness_probe", None)
    return probe if callable(probe) else None


def _remove_worktree(worktree: str) -> tuple[bool, str]:
    """回收工作树目录（不带 --force）；失败只回报事实，不回滚已完成的收口。"""
    try:
        proc = subprocess.run(
            ["git", "worktree", "remove", worktree],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:200]
    if proc.returncode != 0:
        return False, ((proc.stderr or proc.stdout or "").strip())[:200]
    return True, ""


def run_lane_reap(ctx: Any, host: Any, args: dict) -> ToolResult:
    """lane 生命周期收尾（P2）。默认 dry_run=true：零写账本、零动工作树。"""
    store = _store(host)
    if store is None:
        return _fail("audit_dir 未装配，lane 账本不可用", "lane_reap", "store_unavailable")
    dry_run = bool(args.get("dry_run", True))
    remove_worktree = bool(args.get("remove_worktree", False))
    confirm = bool(args.get("confirm", False))
    try:
        ttl_hours = float(args.get("ttl_hours", 168))
    except (TypeError, ValueError):
        return _fail("ttl_hours 必须是数字（小时）", "lane_reap", "invalid_param")
    try:
        limit = int(args.get("limit", 20))
    except (TypeError, ValueError):
        return _fail("limit 必须是整数", "lane_reap", "invalid_param")
    probe = _liveness_probe(host)
    try:
        result = store.reap_candidates(
            ttl_hours=ttl_hours,
            limit=limit,
            liveness_probe=probe,
            tree_probe=_probe_tree_state,
        )
    except LaneStoreCorruptionError as exc:
        return _fail(str(exc), "lane_reap", "store_corruption")
    except OSError as exc:
        return _fail(f"账本读取失败: {exc}", "lane_reap", "io_error")

    candidates = result.get("candidates") or []
    counts = result.get("counts") or {}
    scanned = result.get("scanned")
    liveness_ok = bool(result.get("liveness_available"))

    if dry_run:
        lines = [
            f"[lane_reap dry-run] 扫描在途 {scanned} 条，超时候选 {len(candidates)} 条"
            f"（conclusive {counts.get('conclusive', 0)} / suspect {counts.get('suspect', 0)}"
            f" / unavailable {counts.get('unavailable', 0)}）；"
            f"liveness_available={liveness_ok}；dry_run 不写账本、不动工作树。"
        ]
        for cand in candidates[:10]:
            lines.append(
                f"  - {cand.get('lane_id')} idle={cand.get('idle_hours')}h"
                f" liveness={cand.get('liveness')} tree={cand.get('tree_state')}"
                f" → {cand.get('verdict')}"
            )
        return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", "lane_reap")

    if not liveness_ok:
        return ToolResult(
            ToolResultStatus.SUCCESS,
            "[liveness_unavailable] 无可用 liveness 谓词，零动作（fail-closed："
            "超时≠死亡，探不到不等于已死）。"
            f"扫描在途 {scanned} 条，超时候选 {len(candidates)} 条，全部未处理。",
            "",
            "lane_reap",
        )

    closed: list[str] = []
    flagged: list[str] = []
    kept: list[dict] = []
    removed: list[str] = []
    pending_remove: list[dict] = []
    conflicts: list[dict] = []
    for cand in candidates:
        lane_id = str(cand.get("lane_id") or "")
        verdict = str(cand.get("verdict") or "")
        if verdict == "conclusive":
            reason = f"reaped:idle={cand.get('idle_hours')}h;liveness=dead;tree=clean"
            try:
                res = store.close_if_live(lane_id, status="abandoned", reason=reason)
            except LaneConstraintError as exc:
                conflicts.append(
                    {"lane_id": lane_id, "result": "constraint_violation", "detail": str(exc)}
                )
                continue
            except (OSError, LaneStoreCorruptionError) as exc:
                conflicts.append({"lane_id": lane_id, "result": "io_error", "detail": str(exc)})
                continue
            if res.get("closed"):
                closed.append(lane_id)
                worktree = str(cand.get("worktree") or "")
                if remove_worktree and confirm and worktree:
                    ok, detail = _remove_worktree(worktree)
                    if ok:
                        removed.append(lane_id)
                    else:
                        store.append_lane_event(
                            "lane.worktree_kept", lane_id=lane_id, detail=detail
                        )
                        kept.append({"lane_id": lane_id, "detail": detail})
                else:
                    pending_remove.append({"lane_id": lane_id, "worktree": worktree})
            else:
                result_kind = (
                    "conflict"
                    if res.get("conflict")
                    else str(res.get("already") or res.get("missing") or "unknown")
                )
                conflicts.append({"lane_id": lane_id, "result": result_kind})
        elif verdict == "suspect":
            store.append_lane_event(
                "lane.stale_suspected",
                lane_id=lane_id,
                idle_hours=cand.get("idle_hours"),
                liveness=cand.get("liveness"),
                tree_state=cand.get("tree_state"),
            )
            flagged.append(lane_id)

    lines = [
        f"[lane_reap applied] 扫描在途 {scanned} 条，超时候选 {len(candidates)} 条；"
        f"已收口 {len(closed)}、标疑 {len(flagged)}、未处理/冲突 {len(conflicts)}、"
        f"已回收工作树 {len(removed)}、待人工清理 {len(pending_remove)}、工作树保留 {len(kept)}。"
    ]
    for lane_id in closed:
        lines.append(f"  - 已收口 abandoned: {lane_id}")
    for lane_id in flagged:
        lines.append(f"  - 标疑（状态与目录均未动）: {lane_id}")
    for item in conflicts:
        lines.append(f"  - 未处理 {item.get('result')}: {item.get('lane_id')}")
    for item in kept:
        lines.append(f"  - 工作树保留: {item.get('lane_id')}（{item.get('detail')}）")
    for lane_id in removed:
        lines.append(f"  - 工作树已回收: {lane_id}")
    for item in pending_remove:
        lines.append(
            f"  - 待人工清理（D2：收口≠清理，默认不删目录）: git worktree remove "
            f"{item.get('worktree')}  # lane {item.get('lane_id')}"
        )
    return ToolResult(ToolResultStatus.SUCCESS, "\n".join(lines), "", "lane_reap")
