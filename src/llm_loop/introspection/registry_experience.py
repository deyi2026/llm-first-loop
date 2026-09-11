"""经验库类工具注册（T2，design §2.1.2-5.2）.

承载: save_experience / refine_experience
AI 优先：程序仅通道，提取/判断归 AI。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost

_SAVE_EXPERIENCE_TOOL_DEF: dict[str, Any] = {
    "name": "save_experience",
    "description": "沉淀学习记录到经验库。必须显式区分 record_kind=experience（已有证据证明生效的正向经验）或 lesson（失败/未验证/已证伪教训），并声明 verification_state；程序只验结构与证据存在，不替模型判断语义真伪。成功回执返回 stable experience:<id>。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "经验标题（生成文件名 slug）"},
            "scenario": {"type": "string", "description": "触发场景"},
            "solution": {"type": "string", "description": "解决方案"},
            "record_kind": {
                "type": "string",
                "enum": ["experience", "lesson"],
                "description": "experience=已验证正向经验；lesson=失败/未验证/已证伪教训",
            },
            "verification_state": {
                "type": "string",
                "enum": ["verified", "unverified", "disproven"],
                "description": "当前记录的验证状态；experience 必须为 verified",
            },
            "root_cause": {"type": "string", "description": "根因（可选）"},
            "evidence": {
                "type": "string",
                "description": "证据引用；verified/disproven 时必填",
            },
            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签（可选）"},
            "source": {"type": "object", "description": "来源溯源（可选）"},
            "body": {"type": "string", "description": "经验正文原文（可选）"},
        },
        "required": ["title", "scenario", "solution", "record_kind", "verification_state"],
    },
}

_METHOD_MANAGE_TOOL_DEF: dict[str, Any] = {
    "name": "method_manage",
    "description": (
        "Method Learning 生命周期入口：保存 candidate、记录独立 qualification、或显式流转状态。"
        "不自动 promotion，不判断当前任务适用性，不保存隐藏思维链。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save_candidate", "record_qualification", "refine"],
                "description": "动作类型",
            },
            "method_ref": {"type": "string", "description": "qualification/refine 的 method:<id>"},
            "name": {"type": "string", "description": "save_candidate: Method 名称"},
            "description": {"type": "string", "description": "save_candidate: 触发条件/用途简介"},
            "body": {"type": "string", "description": "save_candidate: 完整 Method Card"},
            "parent_ref": {"type": "string", "description": "save_candidate: 修订来源 method ref（可选）"},
            "verdict": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"]},
            "mechanism": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"]},
            "task_benefit": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"]},
            "promotion": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"]},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "note": {"type": "string"},
            "transition": {
                "type": "string",
                "enum": ["qualify", "activate", "hold", "invalidate", "retire", "reopen"],
                "description": "refine: 显式生命周期动作",
            },
        },
        "required": ["action"],
    },
}

_REFINE_EXPERIENCE_TOOL_DEF: dict[str, Any] = {
    "name": "refine_experience",
    "description": "经验生命周期流转入口。archive/invalidate/restore 显式流转记录；experience_id 接受 stable experience:<id>、裸 ID 或 .md。使用结果日志暂不提供，避免形成无界 append-only 堆积。",
    "parameters": {
        "type": "object",
        "properties": {
            "experience_id": {
                "type": "string",
                "description": "经验标识：推荐 stable experience:<id>；兼容裸 ID 或 <id>.md",
            },
            "action": {
                "type": "string",
                "enum": ["archive", "invalidate", "restore"],
            },
        },
        "required": ["experience_id", "action"],
    },
}


def tool_defs() -> list[dict]:
    return [_SAVE_EXPERIENCE_TOOL_DEF, _REFINE_EXPERIENCE_TOOL_DEF, _METHOD_MANAGE_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "save_experience":
        return _run_save_experience(args, host)
    if name == "refine_experience":
        return _run_refine_experience(args, host)
    if name == "method_manage":
        return _run_method_manage(args, host)
    return None


def _run_save_experience(args: dict, host: RegistryHost) -> ToolResult:
    store = host.experience_store
    if store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[程序异常] 经验库未装配（experience_store 未注入）",
            tool_call_id="",
            tool_name="save_experience",
        )
    from llm_loop.introspection.tools_experience import run_save_experience

    content = run_save_experience(
        store,
        title=args.get("title", ""),
        scenario=args.get("scenario", ""),
        solution=args.get("solution", ""),
        record_kind=args.get("record_kind", ""),
        verification_state=args.get("verification_state", ""),
        root_cause=args.get("root_cause", ""),
        evidence=args.get("evidence", ""),
        tags=args.get("tags") or [],
        source=args.get("source") or {},
        body=args.get("body", ""),
    )
    status = ToolResultStatus.SUCCESS if content.startswith("[save_experience]") else ToolResultStatus.FAILURE
    return ToolResult(status=status, content=content, tool_call_id="", tool_name="save_experience")


def _run_refine_experience(args: dict, host: RegistryHost) -> ToolResult:
    store = host.experience_store
    if store is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[程序异常] 经验库未装配（experience_store 未注入）",
            tool_call_id="",
            tool_name="refine_experience",
        )
    from llm_loop.introspection.tools_experience import run_refine_experience

    content = run_refine_experience(
        store,
        experience_id=args.get("experience_id", ""),
        action=args.get("action", ""),
    )
    status = ToolResultStatus.SUCCESS if content.startswith("[refine_experience]") else ToolResultStatus.FAILURE
    return ToolResult(status=status, content=content, tool_call_id="", tool_name="refine_experience")


def _run_method_manage(args: dict, host: RegistryHost) -> ToolResult:
    action = str(args.get("action", "")).strip()
    if action == "save_candidate":
        return _run_save_method_candidate(args, host, tool_name="method_manage")
    if action == "record_qualification":
        return _run_record_method_qualification(args, host, tool_name="method_manage")
    if action == "refine":
        forwarded = dict(args)
        forwarded["action"] = str(args.get("transition", "")).strip()
        return _run_refine_method(forwarded, host, tool_name="method_manage")
    return _method_failure("method_manage", "[参数错误] action 必须为 save_candidate/record_qualification/refine")


def _method_failure(tool_name: str, content: str) -> ToolResult:
    return ToolResult(status=ToolResultStatus.FAILURE, content=content, tool_call_id="", tool_name=tool_name)


def _run_save_method_candidate(args: dict, host: RegistryHost, *, tool_name: str = "save_method_candidate") -> ToolResult:
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    name = str(args.get("name", "")).strip()
    description = str(args.get("description", "")).strip()
    body = str(args.get("body", "")).strip()
    if not name or not description or not body:
        return _method_failure(tool_name, "[参数错误] name/description/body 均为必填")
    try:
        from llm_loop.core.run_context import current_model_label

        episode_ref = str(host.current_episode_ref() or "")
        if not episode_ref.startswith("episode:"):
            return _method_failure(tool_name, "[Method candidate 写入失败] 当前 Episode provenance 不可用")
        record = store.save_candidate(
            name=name,
            description=description,
            body=body,
            source_model=current_model_label.get(),
            source_episode_refs=[episode_ref] if episode_ref else [],
            evidence_refs=[str(v) for v in (args.get("evidence_refs") or [])],
            parent_ref=str(args.get("parent_ref", "")),
        )
    except (OSError, ValueError, RuntimeError) as exc:
        return _method_failure(tool_name, f"[Method candidate 写入失败] {type(exc).__name__}: {exc}")
    host.audit("save_method_candidate", {"method_ref": record.method_ref, "content_hash": record.content_hash}, "success")
    return ToolResult(status=ToolResultStatus.SUCCESS, content=f"[save_method_candidate] {record.method_ref} status=candidate content_hash={record.content_hash}", tool_call_id="", tool_name=tool_name)


def _run_record_method_qualification(args: dict, host: RegistryHost, *, tool_name: str = "record_method_qualification") -> ToolResult:
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    method_ref = str(args.get("method_ref", "")).strip()
    if not method_ref:
        return _method_failure(tool_name, "[参数错误] method_ref 为必填")
    try:
        # Qualification identity is a runtime fact, never a model declaration.
        # Extra/legacy caller ``task_ref`` is intentionally ignored.
        task_ref = str(host.current_episode_ref() or "")
        if not task_ref.startswith("episode:"):
            return _method_failure(tool_name, "[Method qualification 写入失败] 当前 Episode provenance 不可用")
        entry = store.record_qualification(
            method_ref,
            task_ref=task_ref,
            verdict=str(args.get("verdict", "not_evaluated")),
            mechanism=str(args.get("mechanism", "not_evaluated")),
            task_benefit=str(args.get("task_benefit", "not_evaluated")),
            promotion=str(args.get("promotion", "not_evaluated")),
            evidence_refs=[str(v) for v in (args.get("evidence_refs") or [])],
            note=str(args.get("note", "")),
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return _method_failure(tool_name, f"[Method qualification 写入失败] {type(exc).__name__}: {exc}")
    host.audit(
        "record_method_qualification",
        {"method_ref": method_ref, "qualification_episode_ref": task_ref, "verdict": entry["verdict"]},
        "success",
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[record_method_qualification] {method_ref} "
            f"qualification_episode_ref={task_ref} verdict={entry['verdict']} promotion={entry['promotion']}"
        ),
        tool_call_id="",
        tool_name=tool_name,
    )


def _run_refine_method(args: dict, host: RegistryHost, *, tool_name: str = "refine_method") -> ToolResult:
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    method_ref = str(args.get("method_ref", "")).strip()
    action = str(args.get("action", "")).strip()
    target = {"qualify": "qualified", "activate": "active", "hold": "hold", "invalidate": "invalidated", "retire": "retired", "reopen": "candidate"}.get(action)
    if not method_ref or target is None:
        return _method_failure(tool_name, "[参数错误] method_ref 必填且 action 必须为 qualify/activate/hold/invalidate/retire/reopen")
    try:
        record = store.update_status(method_ref, target)
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        return _method_failure(tool_name, f"[Method 生命周期更新失败] {type(exc).__name__}: {exc}")
    host.audit("refine_method", {"method_ref": method_ref, "status": record.status}, "success")
    return ToolResult(status=ToolResultStatus.SUCCESS, content=f"[refine_method] {method_ref} status={record.status}", tool_call_id="", tool_name=tool_name)
