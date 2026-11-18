"""合并队列与 S1 机检的模型侧工具面（DESIGN-20261105 §4.4）。

设计约束:
- 只排队、只机检、只建议; 绝不执行 git merge / push / rebase（S0 边界）。
- 只读工具零写副作用: lane_queue_status / lane_merge_advice / lane_gate_check
  不落任何账本（lane_gate_check 是纯函数, 不读文件）。
- 写工具一律要 expected_version 或显式 reason; 冲突走 CAS 拒绝, 不静默覆盖。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.lane import LaneStore, LaneStoreConfigError
from llm_loop.introspection.lane_gate import (
    GateConfig,
    S1Evidence,
    evaluate_s1_gate,
    should_auto_rollback,
)
from llm_loop.introspection.merge_queue import (
    VERIFY_LAYER_DISABLED,
    MergeQueueConstraintError,
    MergeQueueStore,
    MergeQueueVersionConflictError,
    build_merge_advice,
)
from llm_loop.introspection.tools_lane import lane_store_from_host

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
    """P1-B（2026-11-16 首轮核验）: 与 lane 工具入口同一配置源——复用
    lane_store_from_host（宿主 lane_lock_strict / lane_enforce_cross_goal /
    lane_repo_root 生效），不再默认 warn 构造。INV-1/INV-2 配置非法时抛
    LaneStoreConfigError，由调用方转为显式回执（不静默降级、不崩进程）。
    OSError（audit 目录不可读）仍返回 None=不可用。"""
    return lane_store_from_host(host)


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
        "注意 reason_code=verify_layer_not_enabled 时不要盲目重试: 该码表示层内"
        "尚无任何凭证——先使用 merge_review_start 启动受管只读审查，"
        "取得独立 PASS 后调用 verify_receipt_request，经已登录 Web 人工批准"
        "由 Host 专用签发（verify_ref={lane_id}:{base_sha 前8}）；"
        "再带凭证 submit；无凭证重试只会再消耗一条不可逆的 failed 队列项。"
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
            "with_impact": {"type": "boolean", "description": "可选只读 B2 基线影响投影，默认关闭；仅提示不授权"},
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


def _contract_same_key_hint_note(lanes: Any, lane: dict, lane_id: str) -> tuple[list, str]:
    """M4-A（DESIGN-20261116 §6）: contract_changes 同键提示（hint + 渲染说明行）。

    纯提示、零阻断、零审批，不改任何既有判定；同键 ≠ 设计冲突（语义由模型/人
    判）；不读 approved_by/自报理由（本提示无任何授权语义）。计算失败只降级为
    无提示（不得影响入队主流程）。
    """
    hint: list = []
    try:
        hint = lanes.contract_same_key_hint(
            mine=[str(k) for k in lane.get("contract_changes") or []],
            exclude_lane_id=lane_id,
        )
    except Exception:  # noqa: BLE001 — 提示失败不得影响入队主流程
        hint = []
    if not hint:
        return hint, ""
    rendered = []
    for h in hint[:8]:
        key = str(h.get("key") or "")
        other = str(h.get("lane_id") or "")
        goal = str(h.get("goal_id") or "")
        rendered.append(f"{key} ← {other}(goal={goal})")
    note = (
        "contract 同键声明提示（非冲突结论）: "
        + "; ".join(rendered)
        + "（同键≠设计冲突，语义由模型/人判；纯提示，不阻断、不审批）"
    )
    return hint, note


def run_lane_queue_submit(ctx: Any, host: Any, args: dict) -> ToolResult:
    tool = "lane_queue_submit"
    lane_id = str(args.get("lane_id") or "").strip()
    if not lane_id:
        return _fail("lane_id 必填", tool, "missing_param")
    store = _store(host, args.get("repo_root"))
    try:
        lanes = _lanes(host)
    except LaneStoreConfigError:
        # P1-B: 宿主 lane 严格配置非法（INV-1/INV-2）→ 显式失败，不静默降级；
        # 异常原文可能携带宿主路径/配置细节，回执只保留结构化 reason code。
        return _fail("lane store 配置非法（invalid_config）", tool, "invalid_config")
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
    # M4-A（DESIGN-20261116 §6）: contract_changes 同键提示——纯提示、零阻断、
    # 零审批，不改任何既有判定；同键 ≠ 设计冲突（语义由模型/人判）；不读
    # approved_by/自报理由（本提示无任何授权语义）。计算失败只降级为无提示。
    same_key_hint, same_key_note = _contract_same_key_hint_note(lanes, lane, lane_id)
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
    except MergeQueueVersionConflictError as exc:
        # CAS 冲突（并发入队/并发改状态）：渲染成可自愈的 FAILURE，而不是冒泡成异常。
        return _fail(
            f"版本冲突（队列项已被并发修改）: {exc}；请先 lane_queue_status 重新读取",
            tool,
            "version_conflict",
        )
    except MergeQueueConstraintError as exc:
        try:
            existing = store.get(lane_id)
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            dup_payload: dict[str, Any] = {"entry": existing, "note": "已在队列中, 未重复登记"}
            if same_key_hint:
                dup_payload["contract_same_key_hint"] = same_key_hint
                dup_payload["contract_same_key_note"] = same_key_note
            return _ok(
                dup_payload,
                tool,
                f"[已在队列] lane={lane_id} status={existing.get('status')}",
            )
        return _fail(str(exc), tool, "constraint_violation")
    except OSError as exc:
        return _fail(f"队列账本写入失败: {exc}", tool, "io_error")

    staged = store.request_preflight(lane_id, expected_version=entry["version"])
    if not staged.get("ok"):
        staged_payload: dict[str, Any] = {
            "entry": staged.get("entry"),
            "holder": staged.get("holder"),
        }
        if same_key_hint:
            staged_payload["contract_same_key_hint"] = same_key_hint
            staged_payload["contract_same_key_note"] = same_key_note
        return _ok(
            staged_payload,
            tool,
            f"[已排队, 机检未开始] {staged.get('reason_code')}",
        )
    result = store.run_preflight(lane_id, expected_version=staged["entry"]["version"])
    layer = result.get("verify_layer") or {}
    codes = list(result.get("reason_codes") or [])
    note = ""
    if VERIFY_LAYER_DISABLED in codes:
        # EVO-20261105-501db776: 把「层没启用」和「你的凭证有问题」分开说清楚。
        # 否则调用方会以为补 verify_ref 就能过，实际重试/重验都不会改变结果。
        note = (
            "\n说明: 机检 d 失败原因是 verify 凭证层未启用——"
            f"{layer.get('receipts_path') or 'data/audit/verify_receipts.jsonl'} "
            f"不存在或无任何凭证（file_exists={layer.get('file_exists')}, "
            f"receipt_count={layer.get('receipt_count')}），"
            "Agent 侧不可写受保护审计账本；需走 merge_review_start → "
            "verify_receipt_request → 已登录浏览器批准 → Host 签发。"
            "该 lane 已落 failed 终态，先完成签发再重新登记。"
        )
    final_payload: dict[str, Any] = {"enqueued": entry, "preflight": result}
    if same_key_hint:
        final_payload["contract_same_key_hint"] = same_key_hint
        final_payload["contract_same_key_note"] = same_key_note
    return _ok(
        final_payload,
        tool,
        f"[机检 {result.get('verdict')}] lane={lane_id} status={result.get('status')}"
        f" reason={','.join(codes) or 'none'}{note}",
    )


_LANE_TERMINAL_STATUSES = frozenset({"merged", "closed", "abandoned"})
_LANE_IDENTITY_KEYS = ("branch", "worktree", "goal_id")


def _resolve_lane_versions(lanes: list[dict]) -> list[dict] | None:
    """同 lane_id 多版本行的确定性收敛（fail-closed；B2 可用性修复）。

    账本为 append-only 历史 + 当前态语义（LaneStore: last-write-wins +
    version CAS，见 lane.py 模块头）。仅当同 lane_id 的重复行同时满足：
      1) version 为正整数且按文件顺序严格递增（version CAS：禁回退/并列）；
      2) 身份字段 branch/worktree/goal_id 逐行一致（防漂移冒用同 id）；
      3) 终态（merged/closed/abandoned）不可逆——终态行后不得再有同 id 行；
    才收敛为最新版本行。任何违反（含 version 缺失/非整数）返回 None，
    由调用方整体降级 lane_snapshot_degraded；绝不盲目 last-write-wins。
    """
    groups: dict[str, list[dict]] = {}
    for lane in lanes:
        groups.setdefault(lane["lane_id"], []).append(lane)
    resolved: list[dict] = []
    for rows in groups.values():
        if len(rows) == 1:
            resolved.append(rows[0])
            continue
        prev_version: int | None = None
        for row in rows:
            version = row.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                return None
            if prev_version is not None and version <= prev_version:
                return None
            prev_version = version
            if any(row.get(key) != rows[0].get(key) for key in _LANE_IDENTITY_KEYS):
                return None
            if row is not rows[-1] and row.get("status") in _LANE_TERMINAL_STATUSES:
                return None
        resolved.append(rows[-1])
    return resolved


def _read_impact_lanes(audit_dir: str) -> tuple[list[dict], str]:
    """Never construct LaneStore here: its constructor calls mkdir."""
    if not audit_dir:
        return [], "lane_snapshot_unavailable"
    try:
        lines = (Path(audit_dir) / "lanes.jsonl").read_text(encoding="utf-8").splitlines()
        lanes = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, ValueError):
        return [], "lane_snapshot_degraded"
    if not all(isinstance(lane, dict) and isinstance(lane.get("lane_id"), str)
               for lane in lanes):
        return [], "lane_snapshot_degraded"
    ids = [lane["lane_id"] for lane in lanes]
    if len(set(ids)) != len(ids):
        resolved = _resolve_lane_versions(lanes)
        if resolved is None:
            return [], "lane_snapshot_degraded"
        return resolved, ""
    return lanes, ""


def _status_impact_projection(host: Any, args: dict, rows: list[dict]) -> dict:
    """Optional Board-style groups; source errors degrade, never issue commands."""
    from llm_loop.introspection.baseline_impact import project_baseline_impact

    max_rows = 20
    repo_root = _repo_root(host)
    requested_repo = args.get("repo_root")
    trusted = bool(repo_root) and (
        not requested_repo or Path(str(requested_repo)).expanduser().resolve()
        == Path(repo_root).expanduser().resolve()
    )
    lanes, read_error = _read_impact_lanes(_audit_dir(host))
    if not trusted:
        read_error = "main_identity_untrusted"
    by_id = {lane["lane_id"]: lane for lane in lanes} if not read_error else {}
    groups: dict[str, list[str]] = {
        "current": [], "affected": [], "unknown": [],
        "stale_needs_refresh": [], "carryover_candidate": [],
    }
    items: list[dict] = []
    for row in rows[:max_rows]:
        lane_id = str(row.get("lane_id") or "")
        if read_error or lane_id not in by_id:
            projection = {"lane_id": lane_id, "impact": {
                "status": "unknown",
                "reason_codes": [read_error or "lane_snapshot_unavailable"],
                "recommended_next_step": "hold",
            }, "evidence": {"projection_is_authoritative": False}}
        else:
            try:
                projection = project_baseline_impact(
                    repo_root, by_id[lane_id],
                    caller_main_head=(str(args["main_head"])
                                      if args.get("main_head") is not None else None),
                    peer_lanes=lanes,
                )
            except (OSError, ValueError, RuntimeError):
                projection = {"lane_id": lane_id, "impact": {
                    "status": "unknown", "reason_codes": ["projection_unavailable"],
                    "recommended_next_step": "hold",
                }, "evidence": {"projection_is_authoritative": False}}
        status = projection["impact"]["status"]
        if status not in groups:
            # Never create an unrecognized "safe" group from a future or
            # corrupted projection result; unknown remains non-actionable.
            status = "unknown"
            projection["impact"] = {
                "status": status, "reason_codes": ["projection_status_invalid"],
                "recommended_next_step": "hold",
            }
        groups[status].append(lane_id)
        items.append(projection)
    return {
        "schema_version": 1, "source": "host_local_tracking",
        "projection_is_authoritative": False, "merge_permission": "not_granted",
        "items": items, "groups": groups,
        "counts": {key: len(value) for key, value in groups.items()},
        "total": len(rows), "truncated": len(rows) > max_rows,
        "source_complete": not bool(read_error),
    }


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
    # EVO-20261106-fead950b: 有 stale 项（main 前进作废 base）时提示统一收敛建议，
    # 避免逐 lane 独立审查推送（资格互相作废）。
    stale_count = sum(1 for r in rows if r.get("stale"))
    route_hint = (
        " ⏭ stale×" + str(stale_count) + ": 建议各 lane 依次 merge --no-ff 入本地 main 后统一一次整树 push 审查"
        if stale_count
        else ""
    )
    payload: dict[str, Any] = {
        "main_head": main_head, "slot_holder": holder, "entries": rows,
    }
    if args.get("with_impact") is True:
        payload["impact_projection"] = _status_impact_projection(host, args, rows)
    return _ok(
        payload, tool,
        f"[队列 {len(rows)} 项] main={main_head[:12] or '-'} "
        f"slot={holder_lane or '空闲'}" + route_hint,
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
    # EVO-20261106-fead950b: 多 lane 时建议卡回执带统一收敛路线提示
    hint = str(card.get("push_review_route_hint") or "")
    summary = f"[S0 建议卡] 项数={len(card.get('lanes') or [])}（仅建议, 未执行合并）"
    if hint:
        summary += f"\n[收敛路线] {hint}"
    return _ok(card, tool, summary)


def _autosweep_lane_after_merge(host: Any, queue_entry: dict) -> dict:
    """queue.merged ⇒ lane 落 merged（收口治理③，2026-11-10）。

    2026-11-09 实测反例：queue.merged 已落、lane 停在 merging 卡住所有 main push
    一夜。合并事实由队列给出，lane 的在途状态是同一事实的滞后投影——登记
    merged 时顺手收敛它，reason 引用队列事实（queue_id/merge_commit）可归因。
    lane 账本不可用/找不到 lane/冲突时**不阻断** done 本身，把事实带回执交人工
    lane_close 兜底（拒绝必须基于已证事实，但 done 已是事实，不回滚）。
    """
    try:
        lanes = _lanes(host)
    except LaneStoreConfigError:
        # P1-B: 宿主 strict/enforce 配置非法 → 如实回执不关闭；done 既成事实
        # 不可回滚，也不静默降级为默认 warn 绕过严格锁（fail-closed 不谎称）；
        # 异常原文可能携带宿主路径/配置细节，note 不内嵌原始异常文本。
        return {"closed": False, "note": "lane store 配置非法（不降级，invalid_config）"}
    if lanes is None:
        return {"closed": False, "note": "lane 账本不可用"}
    lane_id = str((queue_entry or {}).get("lane_id") or "")
    queue_id = str((queue_entry or {}).get("queue_id") or "")
    merge_commit = str((queue_entry or {}).get("merge_commit") or "")
    try:
        result = lanes.close_if_live(
            lane_id,
            status="merged",
            reason=(
                f"queue.merged 自动收口（{queue_id or 'queue_id 未记'}；"
                f"merge_commit={merge_commit or 'unrecorded'}）——收口治理③"
                "（2026-11-10）：队列已完成合并，lane 状态滞后投影由登记方收敛，"
                "避免 verifying/merging 僵尸占用 push 门。"
            ),
        )
    except Exception as exc:  # noqa: BLE001 — 自动收口失败不连坐 done
        return {"closed": False, "note": f"close_if_live 异常: {exc}"}
    if result.get("conflict"):
        return {"closed": False, "conflict": True, "note": "CAS 冲突重试用尽（并发写者）"}
    return result


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
    raw_version = args.get("expected_version")
    if raw_version is None:
        return _fail("expected_version 必填（防覆盖他人更新）", tool, "missing_param")
    try:
        version = int(raw_version)
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
            sweep = _autosweep_lane_after_merge(host, entry)
            summary = f"[已登记 merged] lane={lane_id}"
            if sweep.get("closed"):
                summary += "；lane 已自动落终态 merged"
            elif sweep.get("already"):
                summary += f"；lane 已是终态 {sweep['already']}"
            elif not sweep.get("missing"):
                summary += f"；lane 自动收口未成（{sweep.get('note') or 'conflict'}），请人工 lane_close 兜底"
            return _ok({"queue": entry, "lane_autoclose": sweep}, tool, summary)
        entry = store.abort(
            lane_id,
            expected_version=version,
            reason=str(args.get("reason") or "").strip(),
        )
        return _ok(entry, tool, f"[已中止] lane={lane_id}")
    except MergeQueueVersionConflictError as exc:
        return _fail(
            f"版本冲突（队列项已被并发修改）: {exc}；请先 lane_queue_status 重新读取",
            tool,
            "version_conflict",
        )
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
    # S1-08 的数据源：调用方未显式给 help_requests 时，从 L3 收件箱读未决请求。
    # 读不到就保持 None（s1_08 返回 skip + dependency_unavailable，skip ≠ pass）。
    if "help_requests" not in raw:
        try:
            from pathlib import Path as _Path

            from llm_loop.introspection.help_inbox import HelpInbox

            _audit = _audit_dir(host)
            if _audit:
                _data = _Path(_audit)
                raw = {
                    **raw,
                    "help_requests": HelpInbox(
                        _data.parent if _data.name == "audit" else _data
                    ).list_pending(),
                }
        except Exception:  # noqa: BLE001 — 数据源不可用降级为 skip，不拖垮机检
            pass
    # S1Evidence 是 dataclass，不做字段级类型检查：传入 "lane": "x" 会在 check
    # 内部炸出 AttributeError，而不是确定性的 FAILURE 回执。入口先挡一层。
    for key in ("lane", "main", "deployment"):
        val = raw.get(key)
        if val is not None and not isinstance(val, dict):
            return _fail(
                f"evidence.{key} 必须是对象（当前 {type(val).__name__}）", tool, "bad_param"
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
    try:
        verdict = evaluate_s1_gate(evidence, config)
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        # 兜底：畸形字段（如 conflicts 传成非数字）不崩溃，按确定性拒绝处理（fail-closed）。
        return _fail(f"evidence 结构无法判定: {exc}", tool, "bad_param")
    payload: dict[str, Any] = {"gate": verdict}
    if args.get("rollback"):
        main = evidence.main or {}
        # main.broken 是「基线损坏」标记，不等价于「合并后验证 RED」，不得互相冒充。
        # 合并后 RED 必须由调用方显式提供 main_red；未提供时按 false（保守不自动回滚），
        # 并在回执里标明来源，避免把"参数缺失"伪装成"已判定无 RED"。
        main_red_raw = args.get("main_red")
        payload["rollback"] = should_auto_rollback(
            config=config,
            deployment=evidence.deployment,
            main_head=str(main.get("head_sha") or ""),
            main_red=bool(main_red_raw) if main_red_raw is not None else False,
            attribution_precise=bool(args.get("attribution_precise")),
        )
        payload["rollback"]["main_red_source"] = (
            "explicit" if main_red_raw is not None else "absent_default_false"
        )
    return _ok(
        payload,
        tool,
        f"[S1 {verdict.get('verdict')}] auto_denied={verdict.get('auto_denied')}",
    )
