"""goal 收口前置门（自 tools_goal.run_update_goal 抽出，控制单函数行长棘轮）.

语义与 EVO-20260923-6bcc4880 完全一致：complete 是终局裁决书写，任务图未收口或
证据未过真实性校验一律拒绝书写；账本不可读时 fail-closed（拒绝而非照写）。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus


def complete_gate(host: Any, gid: str, args: dict) -> ToolResult | None:
    """complete 前置两道门（任务图收口 + 终局证据）；None = 放行."""
    if not getattr(host, "audit_dir", None):
        return None
    try:
        from llm_loop.introspection.task_store import TaskStore

        _ts = TaskStore(str(host.audit_dir))
        _ok, _detail = _ts.goal_completion_ready(gid)
        if not _ok:
            return ToolResult(
                ToolResultStatus.FAILURE,
                f"[收口拒绝] goal {gid} 任务图仍有 open 任务（{_detail}）。\n"
                "先 task_update 推进终态（done/failed/cancelled）；blocked/failed 的"
                "残留如需放弃，转 cancelled 并在 goal reason 说明，或请人工确认 waive。",
                "",
                "update_goal",
            )
        _tasks = _ts.list_for_goal(gid)
        _unverified = [
            t.task_id
            for t in _tasks
            if t.evidence_required and t.evidence_verification_status != "verified"
        ]
        if _unverified:
            return ToolResult(
                ToolResultStatus.BLOCKED,
                "[终局证据门] reason_code=evidence_unverified\n"
                f"goal {gid} 存在 evidence_required 任务未过真实性校验: "
                f"{', '.join(_unverified[:5])}\n"
                "出口: 补齐 evidence_refs 重新验证，或请人工确认 waive；"
                "证据 verified 前 complete 拒绝书写。",
                "",
                "update_goal",
            )
        if not any(t.status == "done" for t in _tasks):
            # 零依托终局（空任务图/全非 done）: 自报 evidence_refs 过 verifier 才可书写
            _refs = [str(r) for r in args["evidence_refs"]] if args.get("evidence_refs") else []
            if not _refs:
                return ToolResult(
                    ToolResultStatus.BLOCKED,
                    "[终局证据门] reason_code=no_finality_evidence\n"
                    f"goal {gid} 无 done 任务依托，complete 需自报 evidence_refs"
                    "（evidence:// 引用）并通过真实性校验。\n"
                    "出口: 带已核验证据 refs 重试、建任务图推进后收口，或请人工确认 waive。",
                    "",
                    "update_goal",
                )
            _verifier = getattr(getattr(host, "ctx", None), "task_evidence_verifier", None)
            if _verifier is None:
                return ToolResult(
                    ToolResultStatus.BLOCKED,
                    "[终局证据门] reason_code=probe_unavailable\n"
                    "task_evidence_verifier 未装配，无法校验自报 evidence_refs；"
                    "complete 拒绝书写（fail-closed）。\n出口: 修复装配后重试，或请人工确认 waive。",
                    "",
                    "update_goal",
                )
            _report = _verifier.verify(_refs)
            if getattr(_report, "status", "") != "verified":
                return ToolResult(
                    ToolResultStatus.BLOCKED,
                    "[终局证据门] reason_code=evidence_below_threshold\n"
                    f"自报 evidence_refs 校验未通过（status={getattr(_report, 'status', '')}）。\n"
                    "出口: 修正引用后重试，或请人工确认 waive。",
                    "",
                    "update_goal",
                )
    except Exception as exc:  # noqa: BLE001 — EVO-20260923: 账本不可读 → 不写终局（fail-closed）
        return ToolResult(
            ToolResultStatus.BLOCKED,
            f"[终局证据门] reason_code=probe_unavailable\n任务账本不可读（{exc}）；"
            "complete 拒绝书写（fail-closed）。\n出口: 修复账本可读性后重试，或请人工确认 waive。",
            "",
            "update_goal",
        )
    return None
