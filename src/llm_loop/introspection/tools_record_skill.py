"""Record & Replay Stage 1 — 操作序列生成 SKILL.md（EVO-20260813-db25127c）.

Codex 2026-06-19 Record & Replay Stage 1：
- 用户提供 action_log JSON 列表（操作步骤）
- AI 分析公共模式 → 提取参数 vs 固定配置 → 生成 SKILL.md 草案
- 手动审查后用 submit_evolution 提交为正式 Skill

Stage 2（未实施）：GUI 录制（需 pyautogui + macOS 权限）
"""

from __future__ import annotations

from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

RECORD_SKILL_TOOL_DEF: dict = {
    "name": "record_skill",
    "description": "操作序列→SKILL.md 生成器（Record & Replay Stage 1）。何时用: 想把重复操作沉淀为 Skill 但不愿手写 SKILL.md；用户给操作 JSON→自动生成模板。何时不用: 简单任务无需 Skill 化；GUI 录制（需 Stage 2，本工具不支持）。失败对策: action_log 为空/格式错误时如实返回错误。",
    "parameters": {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string", "description": "Skill 名称（snake_case）"},
            "action_log": {"type": "array", "description": "操作日志 JSON 列表，每项含 action/target/args 字段"},
            "parameters_hint": {"type": "array", "items": {"type": "string"}, "description": "提示哪些字段是参数（amount/date 等）"},
            "auto_submit": {"type": "boolean", "description": "自动提交为演进（默认 false=仅生成预览）"},
        },
        "required": ["skill_name", "action_log"],
    },
}


def _detect_pattern(action_log: list[dict]) -> dict:
    """分析操作日志，识别公共模式 + 参数 vs 固定配置."""
    if not action_log:
        return {"common_actions": [], "varying_keys": [], "fixed_keys": []}

    # 统计每个 action 出现的次数
    action_freq: dict[str, int] = {}
    for entry in action_log:
        action = entry.get("action", "")
        action_freq[action] = action_freq.get(action, 0) + 1

    common_actions = [a for a, c in action_freq.items() if c >= 2]

    # 找 args 中变化 vs 不变的字段
    args_keys_freq: dict[str, set] = {}
    for entry in action_log:
        for k, v in (entry.get("args") or {}).items():
            args_keys_freq.setdefault(k, set()).add(str(v))

    # varying: 出现 ≥1 次的 args key（启发式：每次操作都可能是参数）
    # fixed: 仅当某个 key 出现在所有 entry 且值完全一致（更严格才标 fixed）
    if action_log:
        all_keys: set = set()
        for e in action_log:
            all_keys.update((e.get("args") or {}).keys())

        # fixed: 在每个 entry 都出现且值一致
        # varying: 其他（即使只出现 1 次）
        fixed_keys = []
        for k in all_keys:
            present_in_all = all(k in (e.get("args") or {}) for e in action_log)
            if present_in_all:
                values = [str((e.get("args") or {}).get(k)) for e in action_log]
                if len(set(values)) == 1:
                    fixed_keys.append(k)
        fixed_keys = sorted(fixed_keys)
        varying_keys = sorted(all_keys - set(fixed_keys))
    else:
        varying_keys = []
        fixed_keys = []

    return {
        "common_actions": common_actions,
        "varying_keys": varying_keys,
        "fixed_keys": fixed_keys,
        "total_entries": len(action_log),
        "unique_actions": len(action_freq),
    }


def _generate_skill_md(skill_name: str, pattern: dict, action_log: list[dict], parameters_hint: list[str]) -> str:
    """生成 SKILL.md 草案."""
    params = parameters_hint or pattern["varying_keys"]
    fixed = [k for k in pattern["fixed_keys"] if k not in params]

    lines = [
        f"# Skill: {skill_name}",
        "",
        "## Description",
        "",
        f"Auto-generated from {pattern['total_entries']} operations.",
        f"Common actions: {', '.join(pattern['common_actions']) or '(none)'}.",
        "",
        "## Parameters",
        "",
    ]

    if params:
        for p in params:
            lines.append(f"- `{p}`: (varies per call)")
    else:
        lines.append("- (no parameters detected)")

    lines.append("")
    lines.append("## Fixed Configuration")
    lines.append("")
    if fixed:
        for f in fixed:
            sample = next((e.get("args", {}).get(f) for e in action_log if e.get("args")), None)
            lines.append(f"- `{f}`: `{sample}` (固定不变)")
    else:
        lines.append("- (no fixed config detected)")

    lines.append("")
    lines.append("## Steps")
    lines.append("")
    for i, entry in enumerate(action_log, 1):
        action = entry.get("action", "?")
        target = entry.get("target", "?")
        lines.append(f"{i}. **{action}** → `{target}`")
        if entry.get("args"):
            for k, v in entry["args"].items():
                if k in params:
                    lines.append(f"   - {k}: `{k}`  # parameter")
                else:
                    lines.append(f"   - {k}: `{v}`")

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- 本 SKILL.md 由 record_skill 自动生成，请人工审查后提交")
    lines.append("- 提交方式: `submit_evolution` content=本 SKILL.md 全文")
    lines.append("- Stage 2 GUI 录制待后续")

    return "\n".join(lines)


def run_record_skill(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """record_skill: 操作序列→SKILL.md 生成器."""
    skill_name = str(args.get("skill_name", "")).strip()
    if not skill_name:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: skill_name 为空。原因: 必填。建议: 提供 snake_case 名称。",
            tool_call_id="", tool_name="record_skill",
        )

    action_log = args.get("action_log")
    if not isinstance(action_log, list) or not action_log:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: action_log 为空或非列表。原因: 需提供至少 1 个操作日志条目。建议: 提供 [{'action': '...', 'target': '...', 'args': {...}}, ...]",
            tool_call_id="", tool_name="record_skill",
        )

    parameters_hint = args.get("parameters_hint") or []

    pattern = _detect_pattern(action_log)
    skill_md = _generate_skill_md(skill_name, pattern, action_log, parameters_hint)

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"# 📝 SKILL.md 已生成（{skill_name}）\n\n"
            f"## 模式识别\n"
            f"- 总操作数: {pattern['total_entries']}\n"
            f"- 唯一动作: {pattern['unique_actions']}\n"
            f"- 公共动作（出现≥2次）: {', '.join(pattern['common_actions']) or '无'}\n"
            f"- 参数键（变化）: {', '.join(pattern['varying_keys']) or '无'}\n"
            f"- 固定键（不变）: {', '.join(pattern['fixed_keys']) or '无'}\n\n"
            f"## 📄 SKILL.md 草案\n\n```markdown\n{skill_md}\n```\n\n"
            f"💡 提交方式: 复制 SKILL.md → 提交 submit_evolution\n"
            f"⚠️ Stage 1 不录屏——依赖用户提供 action_log JSON\n"
        ),
        tool_call_id="",
        tool_name="record_skill",
    )
