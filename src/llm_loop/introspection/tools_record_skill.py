"""Record & Replay Stage 1 — 操作序列生成 SKILL.md（EVO-20260813-db25127c）.

Codex 2026-06-19 Record & Replay Stage 1：
- 用户提供 action_log JSON 列表（操作步骤）
- AI 分析公共模式 → 提取参数 vs 固定配置 → 生成 SKILL.md 草案（含 Applicability 适用边界段）
- 提交: auto_submit=true 自动提交（EVO-20260919-7e8e4b20，先过未解决 TODO 前置门）
  或人工审查后 submit_evolution content=SKILL.md 全文

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
            "auto_submit": {"type": "boolean", "description": "自动提交为演进（默认 false=仅生成预览；true 时先过未解决 TODO 前置门，EVO-20260919-7e8e4b20）"},
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

    # EVO-20260919-7e8e4b20: Applicability 适用边界段。
    # 覆盖动作取全集（含仅出现 1 次的动作）；common_actions 只是出现≥2次的子集，不得用作边界。
    action_counts: dict[str, int] = {}
    for entry in action_log:
        _a = str(entry.get("action", "?"))
        action_counts[_a] = action_counts.get(_a, 0) + 1
    covered_actions = ", ".join(f"`{a}`×{c}" for a, c in sorted(action_counts.items())) or "(none)"

    lines.append("")
    lines.append("## Applicability 适用边界")
    lines.append("")
    lines.append(f"- 覆盖动作（全集）: {covered_actions}")
    lines.append(f"- 样本量: {pattern['total_entries']} 个操作 / {pattern['unique_actions']} 种动作")
    if params:
        lines.append("- 覆盖参数键: " + ", ".join(f"`{p}`" for p in params))
    else:
        lines.append("- 覆盖参数键: （无参数）")
    lines.append(
        "- 越界判定: 目标任务的动作不在覆盖全集内、或需要覆盖之外的参数键时，视为超出本 Skill 适用范围；"
        "须人工扩展/重录，不得直接重放"
    )

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
    lines.append("- 本 SKILL.md 由 record_skill 自动生成")
    lines.append(
        "- 提交方式: `record_skill(auto_submit=true)`（含未解决占位符前置门，EVO-20260919-7e8e4b20）"
        "或人工审查后 `submit_evolution` content=本 SKILL.md 全文"
    )
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

    from llm_loop.tools.arg_coerce import coerce_str_list
    parameters_hint = coerce_str_list(args.get("parameters_hint"))

    auto_submit = bool(args.get("auto_submit", False))
    pattern = _detect_pattern(action_log)
    skill_md = _generate_skill_md(skill_name, pattern, action_log, parameters_hint)

    pattern_summary = (
        f"## 模式识别\n"
        f"- 总操作数: {pattern['total_entries']}\n"
        f"- 唯一动作: {pattern['unique_actions']}\n"
        f"- 公共动作（出现≥2次）: {', '.join(pattern['common_actions']) or '无'}\n"
        f"- 参数键（变化）: {', '.join(pattern['varying_keys']) or '无'}\n"
        f"- 固定键（不变）: {', '.join(pattern['fixed_keys']) or '无'}\n"
    )

    if auto_submit:
        # EVO-20260919-7e8e4b20 auto_submit 前置门: 草案含未解决 TODO 时拒绝自动提交
        todo_lines = [ln.strip() for ln in skill_md.splitlines() if "todo" in ln.lower()]
        if todo_lines:
            preview = " | ".join(todo_lines[:3]) + (" ..." if len(todo_lines) > 3 else "")
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[auto_submit 被前置门拦截] 事实: 生成的 SKILL.md 含 {len(todo_lines)} 行未解决 TODO"
                    f"（{preview}）。原因: 含未完成占位符的草案不得自动提交（EVO-20260919-7e8e4b20）。"
                    "建议: 补齐占位内容后重试，或 auto_submit=false 取预览走人工审查。\n\n"
                    f"{pattern_summary}\n"
                    f"```markdown\n{skill_md}\n```"
                ),
                tool_call_id="",
                tool_name="record_skill",
            )
        from llm_loop.introspection.tools_evolution import run_submit_evolution

        submit_result = run_submit_evolution(
            ctx,
            audit,
            {
                "content": skill_md,
                "evidence": (
                    f"record_skill auto_submit（EVO-20260919-7e8e4b20）: "
                    f"{pattern['total_entries']} operations / {pattern['unique_actions']} unique actions; "
                    "Applicability 适用边界段随草案自动生成"
                ),
                "impact_scope": f"skills/{skill_name}",
            },
        )
        if submit_result.status != ToolResultStatus.SUCCESS:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[auto_submit 提交失败] 事实: submit_evolution 未落盘（{skill_name}）。\n"
                    f"{submit_result.content}\n"
                    "建议: 按回执处理（如装配 evolution_store），或 auto_submit=false 取预览人工提交。"
                ),
                tool_call_id="",
                tool_name="record_skill",
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"# 📝 SKILL.md 已自动提交（{skill_name}）\n\n"
                f"{submit_result.content}\n\n"
                f"{pattern_summary}"
            ),
            tool_call_id="",
            tool_name="record_skill",
            capability_requirements=submit_result.capability_requirements or ("submit_evolution",),
        )

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"# 📝 SKILL.md 已生成（{skill_name}）\n\n"
            f"{pattern_summary}\n"
            f"## 📄 SKILL.md 草案\n\n```markdown\n{skill_md}\n```\n\n"
            f"💡 提交方式: 复制 SKILL.md → 提交 submit_evolution，或重跑 record_skill(auto_submit=true) 自动提交（含前置门）\n"
            f"⚠️ Stage 1 不录屏——依赖用户提供 action_log JSON\n"
        ),
        tool_call_id="",
        tool_name="record_skill",
        capability_requirements=("submit_evolution",),
    )
