"""插件化 Skill 工具（B3，2026-08-14）: skill_list / skill_load.

外部 skills/<name>/SKILL.md 目录自动扫描（loader.scan_skills_dir），
AI 经 skill_list 发现、skill_load 把 SKILL.md 全文加载进上下文执行。
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.skills.loader import find_skill, scan_skills_dir

SKILL_LIST_TOOL_DEF: dict = {
    "name": "skill_list",
    "description": "列出可用外部 Skill（skills/ 目录自动扫描，含名称与一句话描述）。何时用: 任务可能命中外部技能库（部署/运维/领域流程等自定义 SKILL.md）时先查清单。何时不用: 内置工具（code_review/grill_me 等）不在列；无需外部技能时不必调用。失败对策: 空清单如实返回空（未配置 skills/ 目录），不伪造技能。",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

SKILL_LOAD_TOOL_DEF: dict = {
    "name": "skill_load",
    "description": "按名加载外部 Skill 全文（SKILL.md，含 frontmatter 与正文）进当前上下文执行。何时用: skill_list 发现目标技能后、执行该技能流程前。何时不用: 未在 skill_list 确认的技能（先 list 再 load）；内置能力无需加载。失败对策: 名称不存在如实报错并列出可用技能；加载失败如实标注。",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名称（skill_list 返回的 name）"},
        },
        "required": ["name"],
    },
}


def _skills_dir(host: Any) -> str | None:
    """从宿主读取 skills 目录（未注入返回 None → 空清单，零回归）."""
    return getattr(host, "skills_dir", None) or None


def run_skill_list(host: Any, args: dict) -> ToolResult:
    """skill_list: 扫描并列出技能（name + description，来源可追溯）."""
    metas = scan_skills_dir(_skills_dir(host))
    if not metas:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="[技能清单] 无外部技能（未配置 skills/ 目录或目录为空）。配置方式: 在 skills/<name>/SKILL.md 放置技能文件。",
            tool_call_id="",
            tool_name="skill_list",
        )
    lines = ["[技能清单] 可用外部技能:"]
    for m in metas:
        lines.append(f"- {m.name}: {m.description}（{m.path}）")
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="\n".join(lines),
        tool_call_id="",
        tool_name="skill_list",
    )


def run_skill_load(host: Any, args: dict) -> ToolResult:
    """skill_load: 按名加载 SKILL.md 全文（frontmatter + 正文）."""
    name = str(args.get("name", "")).strip()
    if not name:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 缺少必填参数 'name'（先用 skill_list 查看可用技能）",
            tool_call_id="",
            tool_name="skill_load",
        )
    meta = find_skill(_skills_dir(host), name)
    if meta is None:
        available = ", ".join(m.name for m in scan_skills_dir(_skills_dir(host)))
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[技能不存在] 未找到技能 '{name}'。可用技能: {available or '（无）'}",
            tool_call_id="",
            tool_name="skill_load",
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"[技能 {meta.name}] {meta.description}\n\n--- SKILL.md 全文 ---\n{meta.body}",
        tool_call_id="",
        tool_name="skill_load",
    )
