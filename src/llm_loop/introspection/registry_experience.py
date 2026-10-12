"""经验库类工具注册（T2，design §2.1.2-5.2）.

承载: save_experience / refine_experience
AI 优先：程序仅通道，提取/判断归 AI。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_model_label
from llm_loop.experiences.store import ExperiencePersistError
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.methods.store import MethodCommitUncertainError, MethodPersistError

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
        "Method Learning 生命周期入口：保存 candidate、声明本任务如何使用 Method、记录独立 qualification、或显式流转状态。"
        "record_use 只保存模型自己的 applied/adapted/not_applicable/rejected 声明；不自动 promotion，不替模型判断适用性，不保存隐藏思维链。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save_candidate", "record_use", "record_qualification", "refine", "annotate_freshness"],
                "description": "动作类型",
            },
            "method_ref": {"type": "string", "description": "record_use/qualification/refine/annotate_freshness 的 method:<id>"},
            "use_decision": {
                "type": "string",
                "enum": ["applied", "adapted", "not_applicable", "rejected"],
                "description": "record_use: 模型声明本任务对该 Method 的处理；不消费评估字段，不会自动 qualification/promotion；有效性由后续独立 qualification 声明",
            },
            "name": {"type": "string", "description": "save_candidate: Method 名称"},
            "description": {"type": "string", "description": "save_candidate: 触发条件/用途简介"},
            "body": {"type": "string", "description": "save_candidate: 完整 Method Card，必须含六个非空节 ## Trigger / ## Discriminator / ## Short path / ## Stop conditions / ## Verification / ## Counterexamples（缺失将拒绝写入）；refine 需持久化的内容也应通过 save_candidate（parent_ref 关联来源）修订"},
            "parent_ref": {"type": "string", "description": "save_candidate: 修订来源 method ref（可选）"},
            "freshness_refs": {"type": "array", "items": {"type": "string"}, "description": "save_candidate/annotate_freshness: 该 Method 依赖的 workspace 相对路径；qualification 时按 SHA 基线化，之后 freshness 只报告 current/changed/missing 事实，不自动降级生命周期。存量卡补声明走 annotate_freshness（只改这一个 frontmatter 键，卡体与其余字段逐字节不变）"},
            "verdict": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "mechanism": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "task_benefit": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "promotion": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "task_type": {"type": "string", "maxLength": 64, "description": "仅 record_qualification 消费：本 qualification 所属任务域的模型声明（如 browser/code-edit/diagnosis/writing；大小写与空白归一，不校验真伪）。activate 门（EVO-20261010-994e30f4）要求 verdict=pass 条目覆盖 ≥2 个不同 task_type 才能转 active；缺省 unknown 不计数。存量 active 卡 grandfather 不回溯"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "save_candidate/record_use/record_qualification 的证据引用；程序将证据绑定到当次调用所属 episode，不自动证明 refs 的归属与内容正确"},
            "note": {"type": "string", "description": "仅 record_use/record_qualification 随记录持久化；save_candidate/refine 不读取、不持久化"},
            "transition": {
                "type": "string",
                "enum": ["qualify", "activate", "hold", "invalidate", "retire", "reopen"],
                "description": "refine: 显式生命周期动作；invalidate/retire 需独立处置依据（一次 qualification verdict=fail，或 ≥2 个不同 episode 的 rejected 使用声明），程序只核事实存在、不判断该 Method 是否该退役；被拒的尝试会落账 journal；reopen 恒可用",
            },
        },
        "required": ["action"],
    },
}

_REFINE_EXPERIENCE_TOOL_DEF: dict[str, Any] = {
    "name": "refine_experience",
    "description": "经验生命周期和使用声明入口。archive/invalidate/restore 显式流转；record_use 声明 applied/adapted/not_applicable/rejected 并落账到经验使用账本 experiences/usage.jsonl（EVO-20261011-945fc53c，锁+fsync+水位，真值源；落账失败如实 FAILURE），事件流仅观察通道。不修改原卡、不自动验证或晋级。experience_id 推荐 stable experience:<id>；声明不是任务收益证明。",
    "parameters": {
        "type": "object",
        "properties": {
            "experience_id": {
                "type": "string",
                "description": "经验标识：推荐 stable experience:<id>；兼容裸 ID 或 <id>.md",
            },
            "action": {
                "type": "string",
                "enum": ["archive", "invalidate", "restore", "record_use"],
            },
            "use_decision": {"type": "string", "enum": ["applied", "adapted", "not_applicable", "rejected"], "description": "record_use 必填；由模型比较任务与经验目的作出判断"},
            "note": {"type": "string", "maxLength": 512, "description": "简短适用依据或跳过理由；不保存隐藏思维链"},
            "evidence_refs": {"type": "array", "maxItems": 16, "items": {"type": "string"}, "description": "声明的证据引用；程序不自动判断正确性"},
        },
        "required": ["experience_id", "action"],
    },
}


METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV = "LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL"
METHOD_SUBJECT_BINDING_SCHEMA = "lfl-method-applicability-subject-binding/v1"
METHOD_SUBJECT_BINDING_TEXT = f"""[{METHOD_SUBJECT_BINDING_SCHEMA}; experimental=1]
当你已在当前任务中精确水合 Method，并需要判断它是否适用于本次 save_experience 时：
- 以当前任务/用户要求里实际要被断言、更新或持久化的 claim subject 为 Trigger / Discriminator / Counterexamples 的判别对象。
- experience record、result/output 文件以及 observation/fixture record 默认只是证据或结果载体；除非任务明确把它们本身作为 claim subject，不得用这些载体替换 claim subject。
- 只匹配当前明确可见的事实；缺失事实不得脑补，本提示不替你选择 applied/adapted/not_applicable/rejected。
- 若已自主决定，继续按现有 method_manage(action=record_use) 规则恰好回记一次；不得仅为本提示新增搜索、取证或工具调用。
[/{METHOD_SUBJECT_BINDING_SCHEMA}]"""
METHOD_SUBJECT_BINDING_COMPACT = (
    f"[{METHOD_SUBJECT_BINDING_SCHEMA}] 保存经验；判断已水合 Method 是否适用时，以当前任务 claim subject 为判别对象；"
    "experience/result/fixture 默认仅为证据载体，不得替换 subject；缺失事实不脑补。"
)


def _method_subject_binding_enabled() -> bool:
    return os.environ.get(METHOD_SUBJECT_BINDING_EXPERIMENTAL_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _save_experience_tool_def() -> dict[str, Any]:
    if not _method_subject_binding_enabled():
        return _SAVE_EXPERIENCE_TOOL_DEF
    row = copy.deepcopy(_SAVE_EXPERIENCE_TOOL_DEF)
    row["description"] = str(row["description"]).rstrip() + "\n" + METHOD_SUBJECT_BINDING_TEXT
    row["compact_description"] = METHOD_SUBJECT_BINDING_COMPACT
    return row


def tool_defs() -> list[dict]:
    return [_save_experience_tool_def(), _REFINE_EXPERIENCE_TOOL_DEF, _METHOD_MANAGE_TOOL_DEF]


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
    # The same prefix also occurs on FileExists and durability-uncertain
    # receipts. Only the exact confirmed-create shape proves the write.
    status = (
        ToolResultStatus.SUCCESS
        if content.startswith("[save_experience] 已沉淀 ")
        and " experience_ref=experience:" in content
        and " status=active " in content
        else ToolResultStatus.FAILURE
    )
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

    if args.get("action") == "record_use":
        return _experience_use_declaration(args, store, host)

    content = run_refine_experience(
        store,
        experience_id=args.get("experience_id", ""),
        action=args.get("action", ""),
    )
    status = (
        ToolResultStatus.SUCCESS
        if content.startswith("[refine_experience] experience:")
        and "状态已更新为 " in content
        else ToolResultStatus.FAILURE
    )
    return ToolResult(status=status, content=content, tool_call_id="", tool_name="refine_experience")


def _experience_use_declaration(args: dict, store: Any, host: RegistryHost) -> ToolResult:
    """EVO-20261011-945fc53c 方案A：使用声明落账 usage ledger（真值源）.

    回执仍带完整 payload（追加 ledger_recorded/ledger_ts/session_id 字段），
    knowledge_runtime 的事件流降级为观察通道——账本落账失败时本工具必须
    如实 FAILURE，不得回退为“只回执不落账”（诚实优先，fail-closed）。
    """
    ref = str(args.get("experience_id") or "").strip()
    decision = str(args.get("use_decision") or "")
    note = args.get("note") or ""
    evidence = args.get("evidence_refs") or []
    if (
        not ref.startswith("experience:") or not ref[11:]
        or decision not in {"applied", "adapted", "not_applicable", "rejected"}
        or not isinstance(note, str) or len(note) > 512
        or not isinstance(evidence, list) or len(evidence) > 16
        or any(not isinstance(e, str) or len(e) > 256 for e in evidence)
    ):
        return _method_failure("refine_experience", "[参数错误] record_use 需要 stable experience ref、use_decision 和有界 note/evidence_refs")
    doc = store.get(ref[11:])
    if doc is None:
        return _method_failure("refine_experience", "[refine_experience] 未找到指定经验；未记录使用声明")

    try:
        entry = store.record_use(
            ref[11:],
            use_decision=decision,
            note=note,
            evidence_refs=evidence,
            episode_ref=str(getattr(host, "current_episode_ref", lambda: "")() or ""),
            session_id=str(getattr(host, "current_session_id", lambda: "")() or ""),
            model=str(current_model_label.get() or ""),
        )
    except ExperiencePersistError as exc:
        return _method_failure(
            "refine_experience",
            f"[refine_experience] 使用声明账本写入确定未提交: {exc}；声明未生效，可重试",
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return _method_failure(
            "refine_experience",
            f"[refine_experience] 使用声明账本写入失败: {type(exc).__name__}: {exc}",
        )
    payload = {
        "schema": "experience-use/v1", "ref": ref, "decision": decision,
        "record_kind": doc.record_kind, "verification_state": doc.verification_state,
        "status": doc.status, "note": note, "evidence_refs": evidence,
        "document_projection_sha256": hashlib.sha256(doc.to_md().encode()).hexdigest(),
        "authority": "model_declared", "task_benefit": "not_evaluated",
        "ledger_recorded": True, "ledger_ts": entry.get("ts", ""),
        "session_id": entry.get("session_id", ""), "episode_ref": entry.get("episode_ref", ""),
    }
    return ToolResult(
        status=ToolResultStatus.SUCCESS, tool_call_id="", tool_name="refine_experience",
        content="[refine_experience] use declaration\n" + json.dumps(payload, ensure_ascii=False),
    )


def _run_method_manage(args: dict, host: RegistryHost) -> ToolResult:
    action = str(args.get("action", "")).strip()
    if action == "save_candidate":
        return _run_save_method_candidate(args, host, tool_name="method_manage")
    if action == "record_use":
        return _run_record_method_use(args, host, tool_name="method_manage")
    if action == "record_qualification":
        return _run_record_method_qualification(args, host, tool_name="method_manage")
    if action == "refine":
        forwarded = dict(args)
        forwarded["action"] = str(args.get("transition", "")).strip()
        return _run_refine_method(forwarded, host, tool_name="method_manage")
    if action == "annotate_freshness":
        return _run_annotate_freshness(args, host, tool_name="method_manage")
    return _method_failure(
        "method_manage", "[参数错误] action 必须为 save_candidate/record_use/record_qualification/refine/annotate_freshness"
    )


def _run_annotate_freshness(args: dict, host: RegistryHost, *, tool_name: str) -> ToolResult:
    """Existing-card freshness_refs channel (EVO-20260929-5283ab1b P5-B follow-up).

    save_candidate is idempotent and never overwrites, so pre-P3 cards could
    not declare freshness_refs without hand-editing frontmatter. This action
    edits exactly that one key via the store and returns the fresh state.
    """
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    method_ref = str(args.get("method_ref", "")).strip()
    if not method_ref.startswith("method:"):
        return _method_failure(tool_name, "[参数错误] method_ref 必须为 method:<id>")
    freshness_refs = [str(v) for v in (args.get("freshness_refs") or [])]
    if not freshness_refs:
        return _method_failure(tool_name, "[参数错误] freshness_refs 不能为空")
    try:
        record = store.annotate_freshness(method_ref, freshness_refs)
    except MethodCommitUncertainError as exc:
        return _method_uncertain_receipt(tool_name, exc)
    except MethodPersistError as exc:
        return _method_failure(tool_name, f"[freshness 注记确定未提交] {exc}；原卡未改，可先核对后重试")
    except (OSError, ValueError, RuntimeError) as exc:
        return _method_failure(tool_name, f"[freshness 注记失败] {type(exc).__name__}: {exc}")
    fresh = store.freshness(method_ref)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[freshness 已注记] {record.method_ref} → {list(record.freshness_refs)}（卡体与其余字段未变）。\n"
            f"当前 freshness 状态: {fresh.get('state')}（SHA 基线在下次 qualification 时落账；freshness 不自动降级生命周期）"
        ),
        tool_call_id="",
        tool_name=tool_name,
    )


def _method_failure(tool_name: str, content: str) -> ToolResult:
    return ToolResult(status=ToolResultStatus.FAILURE, content=content, tool_call_id="", tool_name=tool_name)


def _method_uncertain_receipt(tool_name: str, exc: MethodCommitUncertainError) -> ToolResult:
    """An atomically visible card is not proof of a confirmed durable commit."""
    return _method_failure(
        tool_name,
        f"[Method 提交结果不确定] {exc.method_ref} operation={exc.operation} "
        f"expected_sha256={exc.expected_sha256} visible_state={exc.visible_state}。"
        "目录 fsync 未确认；禁止盲重放。先用 exact method_ref 重新读取卡片 SHA、"
        "status/freshness_refs，若涉及 qualification 还需单独读取 qualification_entries，"
        "再按当前事实决定是否仍需要原动作。",
    )


def _run_save_method_candidate(args: dict, host: RegistryHost, *, tool_name: str = "save_method_candidate") -> ToolResult:
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    name = str(args.get("name", "")).strip()
    description = str(args.get("description", "")).strip()
    body = str(args.get("body", "")).strip()
    if not name or not description or not body:
        return _method_failure(tool_name, "[参数错误] name/description/body 均为必填")
    # EVO-20260923-6fe23c9b F2(a): 强制可执行当前性验证动作
    from llm_loop.introspection.tools_experience import FRESHNESS_ACTION_ERR, freshness_action_ok

    if not freshness_action_ok(description, body):
        return _method_failure(tool_name, FRESHNESS_ACTION_ERR)
    try:

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
            freshness_refs=[str(v) for v in (args.get("freshness_refs") or [])],
        )
    except MethodCommitUncertainError as exc:
        return _method_uncertain_receipt(tool_name, exc)
    except MethodPersistError as exc:
        return _method_failure(tool_name, f"[Method candidate 确定未提交] {exc}；先按 stable id 核对再重试")
    except (OSError, ValueError, RuntimeError) as exc:
        return _method_failure(tool_name, f"[Method candidate 写入失败] {type(exc).__name__}: {exc}")
    host.audit("save_method_candidate", {"method_ref": record.method_ref, "content_hash": record.content_hash}, "success")
    return ToolResult(status=ToolResultStatus.SUCCESS, content=f"[save_method_candidate] {record.method_ref} status=candidate content_hash={record.content_hash}", tool_call_id="", tool_name=tool_name)


def _run_record_method_use(args: dict, host: RegistryHost, *, tool_name: str = "record_method_use") -> ToolResult:
    store = host.method_store
    if store is None:
        return _method_failure(tool_name, "[程序异常] MethodStore 未装配")
    method_ref = str(args.get("method_ref", "")).strip()
    decision = str(args.get("use_decision", "")).strip()
    if not method_ref or not decision:
        return _method_failure(tool_name, "[参数错误] record_use 需要 method_ref/use_decision")
    try:

        episode_ref = str(host.current_episode_ref() or "")
        if not episode_ref.startswith("episode:"):
            return _method_failure(tool_name, "[Method use 写入失败] 当前 Episode provenance 不可用")
        entry = store.record_use(
            method_ref,
            episode_ref=episode_ref,
            decision=decision,
            note=str(args.get("note", "")),
            model=current_model_label.get(),
            evidence_refs=[str(v) for v in (args.get("evidence_refs") or [])],
            session_id=str(host.current_session_id() or ""),
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return _method_failure(tool_name, f"[Method use 写入失败] {type(exc).__name__}: {exc}")
    host.audit(
        "record_method_use",
        {
            "method_ref": method_ref,
            "episode_ref": episode_ref,
            "decision": entry["decision"],
            "method_content_hash": entry["method_content_hash"],
        },
        "success",
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[record_method_use] {method_ref} episode_ref={episode_ref} "
            f"decision={entry['decision']} task_benefit=not_evaluated promotion=not_evaluated"
        ),
        tool_call_id="",
        tool_name=tool_name,
    )


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
            task_type=str(args.get("task_type", "unknown") or "unknown"),
        )
    except MethodCommitUncertainError as exc:
        return _method_uncertain_receipt(tool_name, exc)
    except MethodPersistError as exc:
        return _method_failure(tool_name, f"[Method qualification 确定未提交] {exc}；读取原卡与日志后再重试")
    except (FileNotFoundError, OSError, ValueError) as exc:
        return _method_failure(tool_name, f"[Method qualification 写入失败] {type(exc).__name__}: {exc}")
    host.audit(
        "record_method_qualification",
        {
            "method_ref": method_ref,
            "qualification_episode_ref": task_ref,
            "verdict": entry["verdict"],
            "task_type": entry.get("task_type", "unknown"),
        },
        "success",
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[record_method_qualification] {method_ref} "
            f"qualification_episode_ref={task_ref} verdict={entry['verdict']} promotion={entry['promotion']} "
            f"task_type={entry.get('task_type', 'unknown')}"
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
        record = store.update_status(method_ref, target, episode_ref=str(getattr(host, "episode_ref", "") or ""))
    except MethodCommitUncertainError as exc:
        return _method_uncertain_receipt(tool_name, exc)
    except MethodPersistError as exc:
        return _method_failure(tool_name, f"[Method 生命周期确定未提交] {exc}；原卡未改，先 exact get 核对后重试")
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        # EVO-20260929-5283ab1b P1 (R4): a blocked judgment must not vaporize.
        # update_status already journaled the attempt store-side (universal for
        # every caller); here we only surface the receipt honestly.
        suffix = ""
        if isinstance(exc, ValueError):
            last = None
            for entry in store.attempt_entries(method_ref):
                if entry.get("requested") == target:
                    last = entry
            if last is not None and last.get("journal_persisted"):
                suffix = f"；已落账 lifecycle_transition_attempt（missing_fact={last.get('missing_fact')}）"
        return _method_failure(tool_name, f"[Method 生命周期更新失败] {type(exc).__name__}: {exc}{suffix}")
    host.audit("refine_method", {"method_ref": method_ref, "status": record.status}, "success")
    return ToolResult(status=ToolResultStatus.SUCCESS, content=f"[refine_method] {method_ref} status={record.status}", tool_call_id="", tool_name=tool_name)
