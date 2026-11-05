"""合并队列与 S1 机检的模型侧工具面（DESIGN-20261105 §4.4）。

设计约束:
- 只排队、只机检、只建议; 绝不执行 git merge / push / rebase（S0 边界）。
- 只读工具零写副作用: lane_queue_status / lane_merge_advice / lane_gate_check
  不落任何账本（lane_gate_check 是纯函数, 不读文件）。
- 写工具一律要 expected_version 或显式 reason; 冲突走 CAS 拒绝, 不静默覆盖。
"""
from __future__ import annotations

import json
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.lane_gate import (
    GateConfig,
    S1Evidence,
    evaluate_s1_gate,
    should_auto_rollback,
)
from llm_loop.introspection.merge_queue import (
    MergeQueueConstraintError,
    MergeQueueStore,
    build_merge_advice,
)

_MAX_TEXT = 12000


def _audit_dir(host: Any) -> str:
    return str(host.audit_dir) if getattr(host, "audit_dir", None) else ""


def _repo_root(host: Any, override: object = "") -> str:
    """工作树根: 显式 override 优先, 其次宿主字段, 最后 ctx; 都取不到返回空。

    空值时 MergeQueueStore 的 git 观测只能 skip, 不会伪造 pass。
    """
    text = str(override or "").strip()
    if text:
        return text
    for attr in ("workspace_root", "code_root", "repo_root"):
        val = getattr(host, attr, None)
        if val:
            return str(val)
    ctx = getattr(host, "ctx", None)
    if ctx is not None:
        for attr in ("workspace_root", "code_root"):
            val = getattr(ctx, attr, None)
            if val:
                return str(val)
    return ""


def _store(
    host: Any, repo_override: object = "", *, create: bool = True
) -> MergeQueueStore | None:
    audit_dir = _audit_dir(host)
    if not audit_dir:
        return None
    try:
        return MergeQueueStore(
            audit_dir, repo_root=_repo_root(host, repo_override), create=create
        )
    except OSError:
        return None


def _lanes(host: Any) -> LaneStore | None:
    audit_dir = _audit_dir(host)
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


def _ok(payload: Any, tool: str, summary: str) -> ToolResult:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + "\n…（已截断）"
    return ToolResult(ToolResultStatus.SUCCESS, f"{summary}\n{text}", "", tool)


TOOL_LANE_QUEUE_SUBMIT_DEF: dict[str, Any] = {
    "name": "lane_queue_submit",
    "description": (
        "把已登记 lane 提交到合并队列并立即跑四条机检（S0）。何时用: lane 本地验证完成、"
        "要排队合入 main 时。何时不用: 只想看队列用 lane_queue_status。硬约束: 只排队与"
        "机检, 不执行任何 git 合并/推送; 机检全过 → ready_for_confirm（交还全局串行槽,"
        "等人工确认）。失败对策: merge_slot_busy 表示他人正占用, 看 holder 后重试;"
        "机检不过返回 failed 与 reason_codes, 修复后重新 submit。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane_id": {"type": "string", "description": "已登记的 lane_id"},
            "head_sha": {"type": "string", "description": "缺省取 lane 记录"},
            "base_main_sha": {"type": "string", "description": "缺省取 lane 记录"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "verify_ref": {"type": "string"},
            "repo_root": {"type": "string", "description": "工作树根, 缺省用宿主工作区"},
        },
        "required": ["lane_id"],
    },
}

TOOL_LANE_QUEUE_STATUS_DEF: dict[str, Any] = {
    "name": "lane_queue_status",
    "description": (
        "只读查看合并队列: 每项 status/head/base/stale 与当前全局串行槽持有者。"
        "何时用: 开工前确认是否有人在合并、自己的项是否因 main 前进而 stale。"
        "零写副作用。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "include_terminal": {"type": "boolean", "description": "含 merged/failed/aborted"},
            "main_head": {"type": "string", "description": "缺省现场探测"},
            "repo_root": {"type": "string"},
        },
    },
}

TOOL_LANE_MERGE_ADVICE_DEF: dict[str, Any] = {
    "name": "lane_merge_advice",
    "description": (
        "只读生成 S0 合并建议卡: 建议顺序、冲突面、需重验范围、可一步 revert 性。"
        "何时用: 多条 lane 都完成、要决定先合谁时。不执行合并、不改账本。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "main_head": {"type": "string", "description": "缺省现场探测"},
            "repo_root": {"type": "string"},
        },
    },
}

TOOL_LANE_QUEUE_CONFIRM_DEF: dict[str, Any] = {
    "name": "lane_queue_confirm",
    "description": (
        "人工处置队列项。action=confirm: ready_for_confirm → merging（抢全局串行槽）;"
        "action=done: 登记已合并（merging → merged, 释放槽）; action=abort: 中止并释放槽。"
        "硬约束: 必须给 expected_version 防覆盖他人更新; 本工具不执行 git 操作。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lane_id": {"type": "string"},
            "action": {"type": "string", "enum": ["confirm", "done", "abort"]},
            "expected_version": {"type": "integer"},
            "merge_commit": {"type": "string", "description": "action=done 时登记"},
            "reason": {"type": "string", "description": "action=abort 时必填"},
            "slot_owner": {"type": "string"},
            "repo_root": {"type": "string"},
        },
        "required": ["lane_id", "action", "expected_version"],
    },
}

TOOL_LANE_GATE_CHECK_DEF: dict[str, Any] = {
    "name": "lane_gate_check",
    "description": (
        "只读执行 S1 十条机检（纯函数, 零副作用）: 返回逐条 verdict/reason_code 与整单裁决。"
        "何时用: 自动合并前的合规判定。硬约束: skip 不等于 pass; 开关默认关; 缺证据即不放行。"
        "传 rollback=true 时附带自动回滚判定（只有被部署 sha 仍等于 main head 才 allow）。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "evidence": {"type": "object", "description": "S1Evidence 字段组成的证据"},
            "config": {"type": "object", "description": "GateConfig 覆盖项（默认全关）"},
            "rollback": {"type": "boolean"},
            "attribution_precise": {"type": "boolean"},
        },
        "required": ["evidence"],
    },
}

MERGE_QUEUE_TOOL_DEFS: list[dict] = [
    TOOL_LANE_QUEUE_SUBMIT_DEF,
    TOOL_LANE_QUEUE_STATUS_DEF,
    TOOL_LANE_MERGE_ADVICE_DEF,
    TOOL_LANE_QUEUE_CONFIRM_DEF,
    TOOL_LANE_GATE_CHECK_DEF,
]


def run_lane_queue_submit(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_queue_submit"
    lane_id = str(args.get("lane_id") or "").strip()
    if not lane_id:
        return _fail("lane_id 必填", tool, "missing_param")
    store = _store(host, args.get("repo_root"))
    lanes = _lanes(host)
    if store is None or lanes is None:
        return _fail("audit_dir 未装配或账本不可用", tool, "store_unavailable")
    try:
        lane = lanes.get(lane_id)
    except Exception as exc:  # noqa: BLE001 — 账本损坏按不可用处理
        return _fail(f"读取 lane 失败: {exc}", tool, "store_corruption")
    if lane is None:
        # LaneStore.get 对未知 lane 返回 None（不抛）；这里必须显式拒绝，
        # 否则下面的 lane.get(...) 会 AttributeError，把"未登记"变成进程异常。
        return _fail(
            f"lane 不存在: {lane_id}（未登记不得进入合并队列）", tool, "lane_not_found"
        )
    payload = {
        "lane_id": lane_id,
        "branch": str(args.get("branch") or lane.get("branch") or ""),
        "head_sha": str(args.get("head_sha") or lane.get("head_sha") or ""),
        "base_main_sha": str(
            args.get("base_main_sha") or lane.get("base_main_sha") or ""
        ),
        "paths": list(args.get("paths") or lane.get("paths") or []),
        "verify_ref": str(args.get("verify_ref") or lane.get("verify_ref") or ""),
    }
    try:
        entry = store.enqueue(**payload)
    except MergeQueueConstraintError as exc:
        try:
            existing = store.get(lane_id)
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            return _ok(
                {"entry": existing, "note": "已在队列中, 未重复登记"},
                tool,
                f"[已在队列] lane={lane_id} status={existing.get('status')}",
            )
        return _fail(str(exc), tool, "constraint_violation")
    except OSError as exc:
        return _fail(f"队列账本写入失败: {exc}", tool, "io_error")

    staged = store.request_preflight(lane_id, expected_version=entry["version"])
    if not staged.get("ok"):
        return _ok(
            {"entry": staged.get("entry"), "holder": staged.get("holder")},
            tool,
            f"[已排队, 机检未开始] {staged.get('reason_code')}",
        )
    result = store.run_preflight(lane_id, expected_version=staged["entry"]["version"])
    return _ok(
        {"enqueued": entry, "preflight": result},
        tool,
        f"[机检 {result.get('verdict')}] lane={lane_id} status={result.get('status')}",
    )


def run_lane_queue_status(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_queue_status"
    # 只读：不建目录、不写账本（create=False 保证零写副作用）
    store = _store(host, args.get("repo_root"), create=False)
    if store is None:
        return _fail("audit_dir 未装配或账本不可用", tool, "store_unavailable")
    try:
        entries = store.list(include_terminal=bool(args.get("include_terminal")))
        holder = store.slot_holder()
        main_head = str(args.get("main_head") or "").strip() or store.probe_main_head()
    except Exception as exc:  # noqa: BLE001
        return _fail(f"读取队列失败: {exc}", tool, "store_corruption")
    rows = []
    for entry in entries:
        status = str(entry.get("status") or "")
        base = str(entry.get("base_main_sha") or "")
        rows.append(
            {
                "lane_id": entry.get("lane_id"),
                "branch": entry.get("branch"),
                "status": status,
                "head_sha": entry.get("head_sha"),
                "base_main_sha": base,
                "verify_ref": entry.get("verify_ref"),
                "version": entry.get("version"),
                "stale": bool(main_head)
                and bool(base)
                and base != main_head
                and status in ("queued", "ready_for_confirm"),
            }
        )
    holder_lane = (holder or {}).get("lane_id") if holder else ""
    return _ok(
        {"main_head": main_head, "slot_holder": holder, "entries": rows},
        tool,
        f"[队列 {len(rows)} 项] main={main_head[:12] or '-'} "
        f"slot={holder_lane or '空闲'}",
    )


def run_lane_merge_advice(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_merge_advice"
    # 只读：不建目录、不写账本（create=False 保证零写副作用）
    store = _store(host, args.get("repo_root"), create=False)
    if store is None:
        return _fail("audit_dir 未装配或账本不可用", tool, "store_unavailable")
    try:
        card = build_merge_advice(store, main_head=str(args.get("main_head") or ""))
    except Exception as exc:  # noqa: BLE001
        return _fail(f"生成建议卡失败: {exc}", tool, "advice_failed")
    return _ok(
        card,
        tool,
        f"[S0 建议卡] 项数={len(card.get('lanes') or [])}（仅建议, 未执行合并）",
    )


def run_lane_queue_confirm(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_queue_confirm"
    lane_id = str(args.get("lane_id") or "").strip()
    action = str(args.get("action") or "").strip()
    if not lane_id or action not in ("confirm", "done", "abort"):
        return _fail(
            "lane_id 必填且 action ∈ confirm|done|abort", tool, "missing_param"
        )
    store = _store(host, args.get("repo_root"))
    if store is None:
        return _fail("audit_dir 未装配或账本不可用", tool, "store_unavailable")
    try:
        version = int(args.get("expected_version"))
    except (TypeError, ValueError):
        return _fail("expected_version 必填（防覆盖他人更新）", tool, "missing_param")
    try:
        if action == "confirm":
            res = store.request_merge(
                lane_id,
                expected_version=version,
                slot_owner=str(args.get("slot_owner") or ""),
            )
            if not res.get("ok"):
                return _ok(res, tool, f"[未确认] {res.get('reason_code')}")
            return _ok(res, tool, f"[已确认, 进入 merging] lane={lane_id}")
        if action == "done":
            entry = store.mark_merged(
                lane_id,
                expected_version=version,
                merge_commit=str(args.get("merge_commit") or ""),
            )
            return _ok(entry, tool, f"[已登记 merged] lane={lane_id}")
        entry = store.abort(
            lane_id,
            expected_version=version,
            reason=str(args.get("reason") or "").strip(),
        )
        return _ok(entry, tool, f"[已中止] lane={lane_id}")
    except MergeQueueConstraintError as exc:
        return _fail(str(exc), tool, "constraint_violation")
    except OSError as exc:
        return _fail(f"账本写入失败: {exc}", tool, "io_error")


def run_lane_gate_check(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_gate_check"
    raw = args.get("evidence")
    if not isinstance(raw, dict):
        return _fail(
            "evidence 必须是对象（见 S1Evidence 字段约定）", tool, "missing_param"
        )
    try:
        evidence = S1Evidence(**raw)
    except TypeError as exc:
        return _fail(f"evidence 字段不匹配: {exc}", tool, "bad_param")
    cfg_raw = args.get("config")
    try:
        config = GateConfig(**cfg_raw) if isinstance(cfg_raw, dict) else None
    except TypeError as exc:
        return _fail(f"config 字段不匹配: {exc}", tool, "bad_param")
    verdict = evaluate_s1_gate(evidence, config)
    payload: dict[str, Any] = {"gate": verdict}
    if args.get("rollback"):
        main = evidence.main or {}
        # main.broken 是「基线损坏」标记，不等价于「合并后验证 RED」。
        # 混用会让回滚判定在基线损坏时误判 RED（并吞掉真正的 RED 判定）。
        # 这里保守传 False：只有确实拿到合并后验证结果时才应由调用方置 True。
        payload["rollback"] = should_auto_rollback(
            config=config,
            deployment=evidence.deployment,
            main_head=str(main.get("head_sha") or ""),
            main_red=False,
            attribution_precise=bool(args.get("attribution_precise")),
        )
    return _ok(
        payload,
        tool,
        f"[S1 {verdict.get('verdict')}] auto_denied={verdict.get('auto_denied')}",
    )
