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
from typing import Any

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

LANE_TOOL_DEFS = [
    LANE_OPEN_TOOL_DEF,
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
