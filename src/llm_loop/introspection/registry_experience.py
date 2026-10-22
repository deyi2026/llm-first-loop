"""经验库类工具注册（T2，design §2.1.2-5.2）.

承载: save_experience / refine_experience / method_manage
以及受限结算通道 settlement_pending / settlement_submit（TASK-ac085ab1-004）。
AI 优先：程序仅通道，提取/判断归 AI。
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_model_label, current_run_generation
from llm_loop.experiences.store import ExperiencePersistError
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.settlement import (
    SettlementItem,
    build_pending_settlement,
    submit_settlement_batch,
)
from llm_loop.knowledge_score.runner import spawn_autorun as spawn_knowledge_score_autorun
from llm_loop.methods.store import MethodCommitUncertainError, MethodPersistError
from llm_loop.usage_net import alert_section

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
        "使用无前置条件：检索到的任意 status 卡（含 candidate）读后即可照做；质量标注（candidate/qualified/active/hold）不限制可用性，只在分数与 coverage 完全打平时定先后（active>qualified>candidate>hold），也不阻断 qualify/activate/hold/reopen 流转。"
        "处置态（invalidated 已知失效、retired 已退役）不进检索发现视图，但仍可用 method:<id> 精确读取、也在 inventory 管理目录里可见。"
        "record_use 完全可选，写与不写都不影响后续可用性；它只保存模型自己的 applied/adapted/not_applicable/rejected 声明。不自动 promotion，不替模型判断适用性，不保存隐藏思维链。"
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
            "body": {"type": "string", "description": "save_candidate: 卡片正文。一句话提醒、索引或完整规程都可以；name/description 非空、正文至少有一行非标题内容即可写入。建议至少说清：何时用 / 做什么或看哪里 / 怎么算成功。六节（## Trigger / ## Discriminator / ## Short path / ## Stop conditions / ## Verification / ## Counterexamples）是可选结构，不是准入条件；写法见 docs/METHOD_CARD_WRITING.md。refine 需持久化的内容也应通过 save_candidate（parent_ref 关联来源）修订"},
            "parent_ref": {"type": "string", "description": "save_candidate: 修订来源 method ref（可选）"},
            "aliases": {"type": "array", "items": {"type": "string"}, "description": "save_candidate: 2-6 条检索同义/口语说法（用户真实说法、术语变体），须含本卡 name/description/body 里没有的词。写入时按区分度自检：过短、生命周期通用词、与 name 重复、或池内高频（df 超阈值）的项自动丢弃，并在回执说明原因"},
            "freshness_refs": {"type": "array", "items": {"type": "string"}, "description": "save_candidate/annotate_freshness: 该 Method 依赖的 workspace 相对路径；qualification 时按 SHA 基线化，之后 freshness 只报告 current/changed/missing 事实，不自动降级生命周期。存量卡补声明走 annotate_freshness（只改这一个 frontmatter 键，卡体与其余字段逐字节不变）"},
            "verdict": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "mechanism": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "task_benefit": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "promotion": {"type": "string", "enum": ["pass", "fail", "mixed", "insufficient", "not_evaluated"], "description": "仅 record_qualification 消费；其余 action 忽略"},
            "task_type": {"type": "string", "maxLength": 64, "description": "仅 record_qualification 消费：本 qualification 所属任务域的模型声明（如 browser/code-edit/diagnosis/writing；大小写与空白归一，不校验真伪）。只用于分组统计，不是任何流转的门槛；缺省 unknown"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "description": "save_candidate/record_use/record_qualification 的证据引用；程序将证据绑定到当次调用所属 episode，不自动证明 refs 的归属与内容正确"},
            "note": {"type": "string", "description": "仅 record_use/record_qualification 随记录持久化；save_candidate/refine 不读取、不持久化"},
            "benefit": {
                "type": "string",
                "enum": ["helped", "neutral", "hindered", "unknown", "mixed"],
                "description": "TASK-ac085ab1 record_use 可选模型自评：本任务中观察到什么帮助。与 task_benefit（独立资格评估）分开记录；缺省 unknown，不当失败或零收益",
            },
            "evidence_level": {
                "type": "string",
                "enum": ["model_declared", "observation_linked", "independently_evaluated"],
                "description": "record_use 可选评价依据等级；缺省 model_declared",
            },
            "suggestion": {"type": "string", "maxLength": 2000, "description": "record_use 可选改进建议（需补前提/更新来源/修步骤/规则冲突）"},
            "work_unit_id": {"type": "string", "maxLength": 128, "description": "record_use 可选任务/工作单元绑定；缺省回退当次 episode。用于防跨任务串账与修订链归并"},
            "transition": {
                "type": "string",
                "enum": ["qualify", "activate", "hold", "invalidate", "retire", "reopen"],
                "description": "refine: 显式生命周期动作。qualify/activate/hold 无前置条件（candidate 可一步转 active，无需先攒 qualification）；invalidate/retire 需独立处置依据（一次 qualification verdict=fail，或 ≥2 个不同 episode 的 rejected 使用声明），程序只核事实存在、不判断该 Method 是否该退役；被拒的尝试会落账 journal；reopen 恒可用",
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
            "benefit": {
                "type": "string",
                "enum": ["helped", "neutral", "hindered", "unknown", "mixed"],
                "description": "TASK-ac085ab1 record_use 可选模型自评：本任务中观察到什么帮助。与 task_benefit（独立资格评估）分开记录；缺省 unknown",
            },
            "evidence_level": {
                "type": "string",
                "enum": ["model_declared", "observation_linked", "independently_evaluated"],
                "description": "record_use 可选评价依据等级；缺省 model_declared",
            },
            "suggestion": {"type": "string", "maxLength": 2000, "description": "record_use 可选改进建议"},
            "work_unit_id": {"type": "string", "maxLength": 128, "description": "record_use 可选任务/工作单元绑定；缺省回退当次 episode"},
        },
        "required": ["experience_id", "action"],
    },
}

# ── 受限结算通道（TASK-ac085ab1-004，设计草案 v3「收尾一次提交简短结算」）──
# 条目上限：整批拒绝不截断（超限时回参数错误，不静默截断前 N 条——
# 截断会让模型误以为剩余条目已结算）。
MAX_SETTLEMENT_BATCH_ITEMS = 32

_SETTLEMENT_PENDING_TOOL_DEF: dict[str, Any] = {
    "name": "settlement_pending",
    "description": (
        "任务收尾结算前置查询：返回当前 session 的待结算知识清单——统一检索工具"
        "精确水合的 knowledge_read 读取事件 − 已持久化结算回执，按（工作单元、对象、"
        "读取版本）三元组抵扣。传 work_unit_id（当前 task id）得确定任务窗口 task(id)；"
        "缺省为降级 session 窗口 degraded(session)。覆盖边界：不覆盖 read_file 直读知识文件、"
        "附件内嵌摘录、泛查询命中；清单是事件源可观测范围，不是全部知识接触——事件源外"
        "接触可经 settlement_submit 提交自报条目（self_reported=true，程序校验 ref 存在性）。"
        "回执含 none 两列（事件源无接触/模型自报无接触）与 settled_count。每个有实质工作量的"
        "工作单元收尾调用一次即可，不要每轮轮询；简单问答豁免。"
    ),
    "compact_description": (
        "收尾结算前置：待结算知识清单=精确水合读取事件−已回执（工作单元×对象×版本抵扣）；"
        "不覆盖 read_file 直读/附件/泛查询；缺 work_unit_id 走 degraded(session)；收尾一次即可。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "work_unit_id": {
                "type": "string",
                "maxLength": 128,
                "description": "当前工作单元/任务 id（推荐 get_goal/task 图事实中的 task id）；缺省=降级 session 窗口",
            },
            "self_reported_no_contact": {
                "type": "boolean",
                "description": "模型自报本任务未接触事件源外知识时置 true（进入 none 两列呈现；不冒充事件源观察）",
            },
        },
    },
}

_SETTLEMENT_SUBMIT_TOOL_DEF: dict[str, Any] = {
    "name": "settlement_submit",
    "description": (
        "任务收尾批量结算提交（受限通道）：一次提交 method/experience/rule 的使用反馈，"
        "程序逐条校验（kind/decision/benefit/evidence_level 合法性、ref 存在性）、逐条持久化、"
        "逐条回执 committed|pending|failed（含 slot_id/submission_hash/revision/ledger_watermark）。"
        "两层键由程序派生：同对象同内容重试幂等（返回既有回执）；提交内容改变即按 supersedes 追加修订。"
        "写入结果未知返回 pending 并附 submission_hash 查询提示，先查原结算再决定是否重发，不盲目重发。"
        "批量部分成功不宣称整批原子完成。回执含结算成本观察（settlement_calls/settlement_rounds）。"
        "work_unit_id 缺省时归属 attribution=unresolved：不抵扣任何确定任务的待结算项。"
        "条目上限 32，超限整批拒绝不截断；未采用的普通候选用 not_applicable 并给选择原因，不计为使用失败。"
    ),
    "compact_description": (
        "收尾批量结算：method/experience/rule 使用反馈逐条回执 committed|pending|failed"
        "（slot_id/submission_hash/revision）+结算成本计数；同内容幂等；≤32 条超限整批拒；"
        "无 work_unit_id=unresolved 不抵扣确定任务。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "work_unit_id": {
                "type": "string",
                "maxLength": 128,
                "description": "当前工作单元/任务 id；缺省=归属 unresolved（不抵扣确定任务）",
            },
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "description": "结算条目（上限 32，超限整批拒绝不截断）",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["method", "experience", "rule"]},
                        "ref": {
                            "type": "string",
                            "description": "稳定 ref：method:<id> / experience:<id> / RULE-AI-xx；自报条目程序校验存在性",
                        },
                        "decision": {
                            "type": "string",
                            "enum": ["applied", "adapted", "not_applicable", "rejected"],
                        },
                        "benefit": {
                            "type": "string",
                            "enum": ["helped", "neutral", "hindered", "unknown", "mixed"],
                            "description": "缺省 unknown，不当失败或零收益",
                        },
                        "evidence_level": {
                            "type": "string",
                            "enum": ["model_declared", "observation_linked", "independently_evaluated"],
                            "description": "缺省 model_declared",
                        },
                        "evidence_refs": {
                            "type": "array",
                            "maxItems": 16,
                            "items": {"type": "string"},
                            "description": "证据引用；程序不自动判断正确性",
                        },
                        "note": {"type": "string", "maxLength": 2000, "description": "简短观察/依据"},
                        "suggestion": {"type": "string", "maxLength": 2000, "description": "改进建议"},
                        "read_version": {
                            "type": "string",
                            "description": "来自 settlement_pending 清单条目的 read_version（版本级抵扣需要）",
                        },
                        "self_reported": {
                            "type": "boolean",
                            "description": "事件源外接触的自报条目置 true；程序校验 ref 存在性后落账并标注",
                        },
                    },
                    "required": ["kind", "ref", "decision"],
                },
            },
        },
        "required": ["items"],
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
    return [
        _save_experience_tool_def(),
        _REFINE_EXPERIENCE_TOOL_DEF,
        _METHOD_MANAGE_TOOL_DEF,
        _SETTLEMENT_PENDING_TOOL_DEF,
        _SETTLEMENT_SUBMIT_TOOL_DEF,
    ]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "save_experience":
        return _run_save_experience(args, host)
    if name == "refine_experience":
        return _run_refine_experience(args, host)
    if name == "method_manage":
        return _run_method_manage(args, host)
    if name == "settlement_pending":
        return _run_settlement_pending(args, host)
    if name == "settlement_submit":
        return _run_settlement_submit(args, host)
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
            # TASK-ac085ab1-001: 模型自评/工作单元绑定可选透传；两层键由程序派生
            work_unit_id=str(args.get("work_unit_id", "") or ""),
            benefit=str(args.get("benefit", "") or "unknown"),
            evidence_level=str(args.get("evidence_level", "") or "model_declared"),
            suggestion=str(args.get("suggestion", "") or ""),
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
        # TASK-ac085ab1-001: 两层键回执（程序派生）
        "slot_id": entry.get("slot_id", ""), "submission_hash": entry.get("submission_hash", ""),
        "revision": entry.get("revision", 1), "idempotent": bool(entry.get("idempotent")),
        "benefit": entry.get("benefit", "unknown"),
    }
    # EVO-20261014-7299aec2: 回执附使用净分告警（提醒即止，不裁决）；派生视图 fail-open
    alert = ""
    try:
        alert = alert_section("experience", ref, store.usage_net(ref))
    except Exception:
        alert = ""
    content = "[refine_experience] use declaration\n" + json.dumps(payload, ensure_ascii=False)
    if alert:
        content += "\n" + alert
    return ToolResult(
        status=ToolResultStatus.SUCCESS, tool_call_id="", tool_name="refine_experience",
        content=content,
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
        alias_drops: list[dict] = []
        record = store.save_candidate(
            name=name,
            description=description,
            body=body,
            source_model=current_model_label.get(),
            source_episode_refs=[episode_ref] if episode_ref else [],
            evidence_refs=[str(v) for v in (args.get("evidence_refs") or [])],
            parent_ref=str(args.get("parent_ref", "")),
            freshness_refs=[str(v) for v in (args.get("freshness_refs") or [])],
            aliases=[str(v) for v in (args.get("aliases") or [])] or None,
            alias_drops=alias_drops,
        )
    except MethodCommitUncertainError as exc:
        return _method_uncertain_receipt(tool_name, exc)
    except MethodPersistError as exc:
        return _method_failure(tool_name, f"[Method candidate 确定未提交] {exc}；先按 stable id 核对再重试")
    except (OSError, ValueError, RuntimeError) as exc:
        return _method_failure(tool_name, f"[Method candidate 写入失败] {type(exc).__name__}: {exc}")
    host.audit("save_method_candidate", {"method_ref": record.method_ref, "content_hash": record.content_hash}, "success")
    # Report the gate's decision rather than silently dropping hints: the writer is the
    # only actor who can rephrase an alias into something discriminative. Kept aliases are
    # reported only when present, so an alias-free write keeps the pre-feature receipt
    # byte-identical (duck-typed stores in tests do not have to grow an ``aliases`` field).
    kept_aliases = getattr(record, "aliases", ()) or ()
    alias_note = f" aliases={len(kept_aliases)} kept" if kept_aliases else ""
    if alias_drops:
        reasons = ", ".join(
            f"{d['reason']} df={d['df']} {d['alias']!r}" for d in alias_drops[:3]
        )
        alias_note += f"; dropped {len(alias_drops)}: {reasons}"
    return ToolResult(status=ToolResultStatus.SUCCESS, content=f"[save_method_candidate] {record.method_ref} status=candidate content_hash={record.content_hash}{alias_note}", tool_call_id="", tool_name=tool_name)


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
        # TASK-ac085ab1-001: 模型自评/工作单元绑定可选透传；两层键由程序派生
        entry = store.record_use(
            method_ref,
            episode_ref=episode_ref,
            decision=decision,
            note=str(args.get("note", "")),
            model=current_model_label.get(),
            evidence_refs=[str(v) for v in (args.get("evidence_refs") or [])],
            session_id=str(host.current_session_id() or ""),
            work_unit_id=str(args.get("work_unit_id", "") or ""),
            benefit=str(args.get("benefit", "") or "unknown"),
            evidence_level=str(args.get("evidence_level", "") or "model_declared"),
            suggestion=str(args.get("suggestion", "") or ""),
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
            "slot_id": entry.get("slot_id", ""),
            "submission_hash": entry.get("submission_hash", ""),
            "revision": entry.get("revision", 1),
            "idempotent": bool(entry.get("idempotent")),
        },
        "success",
    )
    # EVO-20261014-7299aec2: 回执附使用净分告警（提醒即止，不裁决）；派生视图 fail-open
    alert = ""
    try:
        alert = alert_section("method", method_ref, store.usage_net(method_ref))
    except Exception:
        alert = ""
    content = (
        f"[record_method_use] {method_ref} episode_ref={episode_ref} "
        f"decision={entry['decision']} task_benefit=not_evaluated promotion=not_evaluated"
    )
    if alert:
        content += "\n" + alert
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name=tool_name,
        method_use_receipt={
            key: str(entry[key])
            for key in ("method_ref", "decision", "episode_ref", "method_content_hash")
            # Fail-open telemetry: a legacy/incomplete trace entry degrades to a
            # partial receipt; record_use itself must never raise (Rule28 遥测
            # 不降级主路径——独立审查 P2-2 修复)。
            if key in entry
        },
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


# ── 受限结算通道执行（TASK-ac085ab1-004）：薄适配层，语义全部在 settlement.py ──


def _settlement_unavailable(tool_name: str, fact: str) -> ToolResult:
    """通道缺件/会话不可归属的零行为回执（不伪造清单、不落任何账）."""
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=f"[结算通道不可用] 事实: {fact}\n建议: 核对装配/会话上下文后重试；不要手工伪造结算或清单。",
        tool_call_id="",
        tool_name=tool_name,
    )


def _settlement_context(host: RegistryHost) -> tuple[Any | None, str]:
    """取 (channel, session_id)；两者任一缺位即由调用方返回零行为回执."""
    channel = host.ctx.settlement
    if channel is None:
        return None, ""
    return channel, str(host.current_session_id() or "")


def _run_settlement_pending(args: dict, host: RegistryHost) -> ToolResult:
    """settlement_pending: 待结算清单 = 读取事件 − 持久化回执（fail-open 投影）."""
    channel, session_id = _settlement_context(host)
    if channel is None:
        return _settlement_unavailable(
            "settlement_pending", "settlement 通道未装配（EventStore 未启用或组件缺失）"
        )
    if not session_id:
        return _settlement_unavailable("settlement_pending", "当前会话不可归属（session_id 为空），不生成清单")
    pending = build_pending_settlement(
        event_store=channel.event_store,
        method_store=channel.method_store,
        experience_store=channel.experience_store,
        session_id=session_id,
        work_unit_id=str(args.get("work_unit_id") or "").strip(),
        model_self_reported_no_contact=bool(args.get("self_reported_no_contact")),
        event_logs_dir=channel.event_logs_dir,
    )
    host.audit(
        "settlement_pending",
        {"work_unit_id": pending["work_unit_id"], "items": len(pending["items"])},
        "success",
    )
    header = (
        f"[settlement_pending] 待结算 {len(pending['items'])} 项 | settled_count={pending['settled_count']} | "
        f"attribution={pending['attribution']} | read_source={pending['read_source']}"
    )
    # 结算成本观察（真实数据派生）：唯一读取键/已抵扣/待结算 + 成本计数位置；
    # settlement_calls/settlement_rounds 属提交回执（每张结算回执携带），此处不重复计算
    read_keys = int(pending["settled_count"]) + len(pending["items"])
    cost_note = (
        f"结算成本观察: 本窗口唯一读取键 {read_keys}，已抵扣 {pending['settled_count']}，"
        f"待结算 {len(pending['items'])}；收尾一次 settlement_submit 批量提交即可"
        "（调用/回合计数随提交回执返回），不要每轮轮询"
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=header + "\n" + cost_note + "\n" + json.dumps(pending, ensure_ascii=False),
        tool_call_id="",
        tool_name="settlement_pending",
    )


def _settlement_items_from_args(raw: Any) -> list[SettlementItem] | str:
    """有界条目解析：超上限整批拒绝（不截断）；结构非法给出首错位置."""
    if not isinstance(raw, list) or not raw:
        return "items 必须为非空数组"
    if len(raw) > MAX_SETTLEMENT_BATCH_ITEMS:
        return (
            f"条目数 {len(raw)} 超上限 {MAX_SETTLEMENT_BATCH_ITEMS}：整批拒绝不截断；"
            "请按 settlement_pending 清单拆分后分批提交"
        )
    items: list[SettlementItem] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            return f"items[{idx}] 必须为对象"
        refs = row.get("evidence_refs")
        if refs is None:
            refs = []
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
            return f"items[{idx}].evidence_refs 必须为字符串数组"
        items.append(
            SettlementItem(
                kind=str(row.get("kind") or "").strip(),
                ref=str(row.get("ref") or "").strip(),
                decision=str(row.get("decision") or "").strip(),
                benefit=str(row.get("benefit") or "unknown"),
                evidence_level=str(row.get("evidence_level") or "model_declared"),
                evidence_refs=tuple(str(r) for r in refs),
                note=str(row.get("note") or ""),
                suggestion=str(row.get("suggestion") or ""),
                supersedes=str(row.get("supersedes") or ""),
                read_version=str(row.get("read_version") or ""),
                self_reported=bool(row.get("self_reported")),
            )
        )
    return items


def _spawn_krate_autorun(host: RegistryHost, repo_root: Path | None = None) -> str:
    """K-Rate 闭环自动触发：committed 结算后后台跑 score+index.

    约束（与 settlement 主路径的隔离）：
    - fire-and-forget：start_new_session 分离进程组，不等待、不阻塞回执；
    - fail-open：本函数任何异常只写 audit（"krate_autorun"/failed）后吞掉，
      结算回执本身绝不受影响；
    - 守卫：LFL_KRATE_AUTORUN=0 总开关；PYTEST_CURRENT_TEST 存在（pytest 内）
      跳过，防单测向真实 data/ 落子；脚本缺失（未随部署携带）静默跳过。
    串行化在脚本内（flock .autorun.lock，忙等上限 KRATE_AUTORUN_WAIT_S），
    幂等性由 score(event_id)/index(全量重建) 保证。
    """
    try:
        from llm_loop.runtime.resolver import legacy_env_snapshot

        env = legacy_env_snapshot()
        if env.get("LFL_KRATE_AUTORUN") == "0":
            return "disabled_env"
        if env.get("PYTEST_CURRENT_TEST"):
            return "skip_pytest"
        root = repo_root or Path(__file__).resolve().parents[3]
        script = root / "tools" / "krate" / "autorun_after_settlement.py"
        if not script.exists():
            return "script_missing"
        proc = subprocess.Popen(  # noqa: S603 — 固定脚本路径，无 shell 拼接
            [sys.executable, str(script)],
            cwd=str(root),
            env={**env, "KRATE_ROOT": str(root)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"spawned_pid={proc.pid}"
    except Exception as exc:  # noqa: BLE001 — hook 不得破坏结算主路径
        with contextlib.suppress(Exception):  # noqa: BLE001 — 审计失败必须 fail-open（不得破坏结算主路径）
            host.audit("krate_autorun", {"error": str(exc)[:300]}, "failed")
        return "spawn_failed"


def _run_settlement_submit(args: dict, host: RegistryHost) -> ToolResult:
    """settlement_submit: 批量结算逐条回执（committed/pending/failed）+ 成本计数."""
    channel, session_id = _settlement_context(host)
    if channel is None:
        return _settlement_unavailable(
            "settlement_submit", "settlement 通道未装配（EventStore 未启用或组件缺失）"
        )
    if not session_id:
        return _settlement_unavailable("settlement_submit", "当前会话不可归属（session_id 为空），不落任何账")
    parsed = _settlement_items_from_args(args.get("items"))
    if isinstance(parsed, str):
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误] {parsed}",
            tool_call_id="",
            tool_name="settlement_submit",
        )
    receipt = submit_settlement_batch(
        items=parsed,
        method_store=channel.method_store,
        experience_store=channel.experience_store,
        event_store=channel.event_store,
        session_id=session_id,
        work_unit_id=str(args.get("work_unit_id") or "").strip(),
        run_id=str(current_run_generation.get() or ""),
        episode_ref=str(host.current_episode_ref() or ""),
        model=str(current_model_label.get() or ""),
        rule_lookup=channel.rule_lookup,
        event_logs_dir=channel.event_logs_dir,
    )
    counts = receipt["counts"]
    # 零 committed 时回执 FAILURE：部分成功/未知不冒充整批成功；逐条事实在 receipts 内
    host.audit(
        "settlement_submit",
        {"work_unit_id": receipt["work_unit_id"], "items": len(parsed), "counts": counts},
        "success" if counts["committed"] else "no_commit",
    )
    if counts["committed"] > 0:
        # K-Rate 闭环：committed 结算后后台触发 score+index（fire-and-forget，
        # fail-open——任何失败只 audit，绝不影响结算回执本身）。
        # 触发结果本身也落 audit（P2-2 可观测性）：script_missing/disabled_env
        # 静默跳过会导致闭环无声死亡；skip_pytest 属预期跳过，不产生噪声。
        autorun_result = _spawn_krate_autorun(host)
        if autorun_result != "skip_pytest":
            host.audit("krate_autorun", {"result": autorun_result}, "triggered")
        # 知识打分闭环：committed 结算产生/更新 use ledger 后立即补一轮打分；
        # 根目录从经验库反推（与当前 workspace 同源），不能用 runner 源码位置，
        # 否则外部工作区部署会扫错 ledger。spawn 内部 fail-open。
        score_root = getattr(
            getattr(channel, "experience_store", None),
            "workspace_root",
            None,
        )
        if spawn_knowledge_score_autorun(score_root):
            host.audit("knowledge_score_autorun", {"result": "spawned"}, "triggered")
    header = (
        f"[settlement_submit] committed={counts['committed']} pending={counts['pending']} "
        f"failed={counts['failed']} | settlement_calls={receipt['settlement_calls']} "
        f"settlement_rounds={receipt['settlement_rounds']} | attribution={receipt['attribution']}"
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS if counts["committed"] > 0 else ToolResultStatus.FAILURE,
        content=header + "\n" + json.dumps(receipt, ensure_ascii=False),
        tool_call_id="",
        tool_name="settlement_submit",
    )
