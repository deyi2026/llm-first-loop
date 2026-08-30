"""Prompt-facing tool eligibility and runtime-health projection.

R8.7 principle: tool availability is a registry fact, not a prompt-visibility grant.
The provider sees a small stable CORE plus tools required by the current task/protocol.
Hidden tools remain discoverable through get_tool_schema/skill tools and are never
unregistered merely to save prompt tokens.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from typing import Any, Iterable


CORE_TOOL_ORDER: tuple[str, ...] = (
    "edit_file",
    "execute_command",
    "get_tool_schema",
    "read_file",
    "search_files",
    "search_records",
    "skill_list",
    "skill_load",
    "web_search",
)

# Deterministic lexical task routing.  It is intentionally conservative: false negatives
# are recoverable through get_tool_schema("*") / get_tool_schema("?keyword"), while false
# positives only add a small task-specific tail after the stable CORE prefix.
TOOL_TASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "web_fetch": ("http://", "https://", "网页", "链接", "url", "抓取", "在线文档", "网页文章"),
    "read_image": ("图片", "截图", "图像", "png", "jpg", "jpeg", "流程图", "界面图"),
    "architecture_status": ("架构状态", "运行状态", "配置状态", "缓存命中", "cache", "health"),
    "search_archive": ("压缩", "找回", "原文", "早期消息", "archive", "归档"),
    "search_docs": ("设计文档", "需求文档", "审计报告", "评估报告", "spec", "docs/", "文档里"),
    "read_evidence": ("evidence:", "证据 ref", "读取证据", "恢复证据"),
    "search_evidence": ("搜索证据", "查证据", "evidence 搜索"),
    "list_evidence": ("证据清单", "列出证据", "evidence list"),
    "schedule": ("提醒", "定时", "分钟后", "小时后", "每天", "每周", "周期"),
    "schedule_cancel": ("取消提醒", "取消定时", "取消 schedule"),
    "job_output": ("后台任务", "任务输出", "查看进度", "job output"),
    "job_kill": ("终止后台", "停止后台", "kill job", "job_kill"),
    "inspect_code": ("代码结构", "有哪些类", "有哪些函数", "ast", "模块结构"),
    "retry_tool": ("重试工具", "retry_tool", "重新执行工具"),
    "adjust_strategy": ("调整策略", "max_iterations", "timeout_s", "history_budget"),
    "save_experience": ("沉淀经验", "保存经验", "经验库"),
    "refine_experience": ("经验过时", "经验失效", "恢复经验"),
    "submit_evolution": ("演进建议", "submit_evolution", "提交演进"),
    "evolution_complete": ("演进完成", "evolution_complete"),
    "generate_evolution_template": ("演进模板", "evolution template"),
    "model_catalog": ("模型目录", "可用模型", "模型列表", "成本档"),
    "switch_model": ("切换模型", "换模型", "更强模型", "本地模型"),
    "send_feishu_message": ("发到飞书", "飞书消息"),
    "create_feishu_doc": ("飞书文档", "创建飞书文档"),
    "send_feishu_attachment": ("飞书附件", "发附件", "发文件"),
    "code_review": ("代码审查", "code review", "review code"),
    "grill_me": ("设计评审", "盘问", "grill"),
    "stop_slop": ("去 ai 味", "stop_slop", "清洗文本"),
    "handoff_now": ("交接", "handoff", "存档进度"),
    "brainstorm_design": ("头脑风暴", "brainstorm"),
    "tdd_red_green": ("tdd", "red-green", "红绿"),
    "design_review": ("设计 review", "design_review"),
    "record_skill": ("生成 skill", "记录 skill", "record_skill"),
    "playwright_test": ("端到端", "e2e", "浏览器测试", "playwright"),
    "playwright_exec": ("浏览器脚本", "登录态", "js 渲染", "playwright"),
    "spawn_subagent": ("子代理", "subagent", "并行调研"),
    "subagent_report": ("子代理报告", "subagent_report"),
    "workflow_run": ("工作流", "workflow", "并行派发"),
    "dsh_task": ("dsh", "deepseek harness", "headless"),
    "dsh_session_read": ("dsh session", "dsh 过程", "dsh_session_read"),
    "fix_loop": ("修复循环", "fix_loop", "自动迭代修复"),
    "task_create": ("创建任务", "拆解子任务", "task_create"),
    "task_update": ("更新任务状态", "task_update"),
    "task_frontier": ("任务图", "frontier", "当前可执行集"),
    "create_goal": ("创建 goal", "新 goal", "create_goal"),
    "checkpoint_goal": ("checkpoint", "里程碑", "保存进度"),
    "get_goal": ("恢复 goal", "当前 goal", "get_goal", "继续上次"),
    "update_goal": ("完成 goal", "goal 完成", "update_goal"),
    "refresh_config": ("刷新配置", "重载配置", "refresh_config"),
    "recover_from_backup": ("从备份恢复", "recovery backup", "recover_from_backup"),
}

_QUARANTINE_REPLACEMENTS: dict[str, tuple[str, ...]] = {
    "playwright_exec": ("web_fetch", "web_search", "skill_load:web-fetch-fast"),
    "playwright_test": ("execute_command",),
}


@dataclass(frozen=True)
class ToolHealth:
    state: str
    reason_code: str = ""
    preferred_next: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.state != "quarantined"


@dataclass(frozen=True)
class ToolProjection:
    schemas: tuple[dict, ...]
    mode: str
    visible_names: tuple[str, ...]
    task_names: tuple[str, ...]
    protocol_names: tuple[str, ...]
    recovery_names: tuple[str, ...]
    quarantined_names: tuple[str, ...]
    original_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "visible_names": list(self.visible_names),
            "task_names": list(self.task_names),
            "protocol_names": list(self.protocol_names),
            "recovery_names": list(self.recovery_names),
            "quarantined_names": list(self.quarantined_names),
            "original_count": self.original_count,
            "visible_count": len(self.visible_names),
        }


def normalize_tool_eligibility_mode(value: str | None) -> str:
    mode = str(value or "enforce").strip().lower()
    return mode if mode in {"off", "shadow", "enforce"} else "enforce"


def runtime_tool_health(name: str) -> ToolHealth:
    """Return cheap runtime health without executing the tool or weakening safety boundaries."""
    if name in {"playwright_exec", "playwright_test"}:
        try:
            available = importlib.util.find_spec("playwright") is not None
        except (ImportError, AttributeError, ValueError):
            available = False
        if not available:
            return ToolHealth(
                state="quarantined",
                reason_code="playwright_python_dependency_missing",
                preferred_next=_QUARANTINE_REPLACEMENTS.get(name, ()),
            )
    return ToolHealth(state="ready")


def _task_relevant_names(user_text: str, all_names: set[str]) -> set[str]:
    text = (user_text or "").lower()
    selected: set[str] = set()
    for name in all_names:
        if name.lower() in text:
            selected.add(name)
    for name, keywords in TOOL_TASK_KEYWORDS.items():
        if name in all_names and any(keyword in text for keyword in keywords):
            selected.add(name)
    return selected


def _active_protocol_names(messages: Iterable[Any], all_names: set[str]) -> set[str]:
    selected: set[str] = set()
    rows = list(messages)[-8:]
    for msg in rows:
        if isinstance(msg, dict):
            tool_name = str(msg.get("tool_name", "") or "")
            tool_calls = msg.get("tool_calls") or []
        else:
            tool_name = str(getattr(msg, "tool_name", "") or "")
            tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_name in all_names:
            selected.add(tool_name)
        for call in tool_calls:
            if isinstance(call, dict):
                fn = call.get("function") or {}
                name = str(fn.get("name", call.get("name", "")) or "")
            else:
                name = str(getattr(call, "name", "") or "")
            if name in all_names:
                selected.add(name)
    return selected


def _recovery_names(messages: Iterable[Any], all_names: set[str]) -> set[str]:
    selected: set[str] = set()
    for msg in list(messages)[-6:]:
        metadata = msg.get("metadata", {}) if isinstance(msg, dict) else getattr(msg, "metadata", {})
        recovery = metadata.get("tool_recovery") if isinstance(metadata, dict) else None
        if not isinstance(recovery, dict):
            continue
        for raw in recovery.get("preferred_next", []) or []:
            name = str(raw).split(":", 1)[0]
            if name in all_names:
                selected.add(name)
    return selected


def project_tool_schemas(
    schemas: list[dict],
    *,
    user_text: str,
    session_messages: Iterable[Any] = (),
    mode: str = "enforce",
) -> ToolProjection:
    """Project registry schemas to stable CORE + current-required tail.

    shadow computes the same decision but returns the original schemas.  off is exact legacy.
    Quarantined tools are hidden only in enforce; direct stale calls are independently guarded
    by ToolRegistry runtime-health preflight.
    """
    normalized = normalize_tool_eligibility_mode(mode)
    if normalized == "off":
        names = tuple(str(s.get("name", "")) for s in schemas if s.get("name"))
        return ToolProjection(tuple(schemas), normalized, names, (), (), (), (), len(schemas))

    # Last schema wins so prefix-layer dynamic full schema can replace its earlier index row.
    by_name = {str(s.get("name", "")): s for s in schemas if s.get("name")}
    all_names = set(by_name)
    task = _task_relevant_names(user_text, all_names)
    protocol = _active_protocol_names(session_messages, all_names)
    recovery = _recovery_names(session_messages, all_names)
    selected = set(CORE_TOOL_ORDER) & all_names
    selected.update(task)
    selected.update(protocol)
    selected.update(recovery)

    quarantined = {
        name for name in selected if not runtime_tool_health(name).available
    }
    selected.difference_update(quarantined)

    core = [by_name[name] for name in CORE_TOOL_ORDER if name in selected]
    core_names = set(CORE_TOOL_ORDER)
    extras = [
        schema
        for schema in schemas
        if str(schema.get("name", "")) in selected
        and str(schema.get("name", "")) not in core_names
    ]
    # Deduplicate prefix-layer index/full duplicates while preserving the later/full schema.
    extra_names: list[str] = []
    for schema in extras:
        name = str(schema.get("name", ""))
        if name and name not in extra_names:
            extra_names.append(name)
    projected = core + [by_name[name] for name in extra_names]
    if not projected and "get_tool_schema" in by_name:
        projected = [by_name["get_tool_schema"]]

    visible = tuple(str(s.get("name", "")) for s in projected if s.get("name"))
    if normalized == "shadow":
        original_names = tuple(str(s.get("name", "")) for s in schemas if s.get("name"))
        return ToolProjection(
            tuple(schemas), normalized, original_names, tuple(sorted(task)),
            tuple(sorted(protocol)), tuple(sorted(recovery)), tuple(sorted(quarantined)), len(schemas)
        )
    return ToolProjection(
        tuple(projected), normalized, visible, tuple(sorted(task)), tuple(sorted(protocol)),
        tuple(sorted(recovery)), tuple(sorted(quarantined)), len(schemas)
    )
