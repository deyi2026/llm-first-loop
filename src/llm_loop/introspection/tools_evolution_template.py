"""skill-creator 增强 — 演进模板生成器（EVO-20260813-dd496f99）.

根据代码 diff / 工具注册 / 经验沉淀 自动生成演进建议模板（含背景/实施/影响/优先级骨架）。
降低 AI 撰写 submit_evolution 的成本。
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

EVOLUTION_TEMPLATE_TOOL_DEF: dict = {
    "name": "generate_evolution_template",
    "description": "自动生成演进建议模板（基于代码 diff/工具注册/经验沉淀）。何时用: 准备提交 submit_evolution 但不想从头写背景/实施/影响段；需快速生成结构化模板以便修改。何时不用: 演进内容已完整，直接 submit_evolution 即可。失败对策: 源码不可访问时（如无 git）返回手动模板骨架。",
    "parameters": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["git_diff", "tools_added", "experience", "manual"], "description": "模板来源（默认 manual）"},
            "title": {"type": "string", "description": "演进标题（简明）"},
            "priority": {"type": "string", "enum": ["P0", "P1", "P2"], "description": "优先级（默认 P1）"},
        },
        "required": ["title"],
    },
}

# 骨架模板（来源不同填充不同字段）
_SKELETON = """# 【{prefix}】{title}

## 背景
{background}

## 实施
{implementation}

## 影响范围
{impact}

## 优先级
{priority}

## 验证
{verification}

## 不变更项
- 安全防护 / 现有 {existing} 流程不变
"""

_PRIORITY_DESC = {
    "P0": "P0（核心功能缺陷/安全风险，需立即处理）",
    "P1": "P1（增强 AI 主动能力/重要 UX 改进）",
    "P2": "P2（长期愿景/低优先）",
}


def _git_diff_summary() -> str:
    """从 git diff 提取变更摘要."""
    try:
        # 最近 1 次 commit diff
        r = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", "--stat"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return "（git diff 失败——可能无 git 仓库）"
        return f"```\n{r.stdout[:1500]}\n```"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "（git 不可用）"


def _tools_added_summary() -> str:
    """从 corrections.py 提取新增工具（启发式：找 _TOOL_DEF as）."""
    try:
        path = "src/llm_loop/introspection/corrections.py"
        with open(path) as f:
            src = f.read()
        # 找所有 _XXX_TOOL_DEF as
        pattern = re.compile(r"(\w+_TOOL_DEF)\s+as\s+_(\w+_TOOL_DEF)")
        matches = pattern.findall(src)
        # 去重
        unique = sorted(set(m[1].lstrip("_") for m in matches))
        return "已注册工具（含本演进未触及）:\n" + "\n".join(f"- {n}" for n in unique)
    except (OSError, FileNotFoundError):
        return "（corrections.py 不可访问）"


def _experience_summary() -> str:
    """从 experiences/ 目录提取最近经验."""
    try:
        from pathlib import Path
        exp_dir = Path("experiences")
        if not exp_dir.exists():
            return "（experiences/ 目录不存在）"
        files = sorted(exp_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        if not files:
            return "（无经验文件）"
        return "最近 5 个经验文件:\n" + "\n".join(f"- {f.name}" for f in files)
    except Exception:
        return "（经验扫描失败）"


def run_generate_evolution_template(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """generate_evolution_template: 自动生成演进模板骨架."""
    title = str(args.get("title", "")).strip()
    if not title:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: title 为空。原因: 必填。建议: 提供简明标题。",
            tool_call_id="", tool_name="generate_evolution_template",
        )
    source = str(args.get("source", "manual")).strip() or "manual"
    priority = str(args.get("priority", "P1")).strip() or "P1"
    if priority not in {"P0", "P1", "P2"}:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误] 事实: priority 收到非法值 '{priority}'。原因: 需为 P0/P1/P2。建议: 提供正确优先级。",
            tool_call_id="", tool_name="generate_evolution_template",
        )

    # 根据 source 填充各段
    if source == "git_diff":
        background = "代码改动（git diff 摘要）:\n" + _git_diff_summary()
        implementation = "（需根据 diff 填具体实施步骤）"
        impact = "（需根据 diff 中涉及的文件路径填影响范围）"
        verification = "（需说明如何验证——单测/回归/E2E）"
        existing = "git diff"
    elif source == "tools_added":
        background = "新增工具（当前注册列表）:\n" + _tools_added_summary()
        implementation = "（需填工具实现细节：参数/返回值/注册位置）"
        impact = "（需填 corrections.py 工具列表 + tests/unit/test_xxx.py）"
        verification = "（需填端到端测试脚本 + 回归测试）"
        existing = "工具注册"
    elif source == "experience":
        background = "经验沉淀（最近经验文件）:\n" + _experience_summary()
        implementation = "（需说明如何将经验转化为代码改动）"
        impact = "（需填哪些模块受益）"
        verification = "（需说明如何在实际场景验证改进）"
        existing = "经验沉淀机制"
    else:  # manual
        background = "（手动填写：本演进要解决的问题 / 痛点）"
        implementation = "（手动填写：具体步骤 + 代码概览）"
        impact = "（手动填写：影响模块 + 文件清单）"
        verification = "（手动填写：测试方法 + 验证结果）"
        existing = "既有流程"

    template = _SKELETON.format(
        prefix="演进建议",
        title=title,
        background=background,
        implementation=implementation,
        impact=impact,
        priority=_PRIORITY_DESC[priority],
        verification=verification,
        existing=existing,
    )

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=f"📝 演进模板已生成（source={source}, priority={priority}）\n\n```markdown\n{template}\n```\n\n💡 提示：复制模板 → 填写空白字段 → 提交 `submit_evolution`。",
        tool_call_id="",
        tool_name="generate_evolution_template",
    )
