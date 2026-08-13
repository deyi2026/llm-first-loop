"""Codex 风格 Skills 工具集（补齐头条文章盘点：Codex装了这10个Skill）.

本轮实施:
- code_review: 多维代码审查工具（5维：正确性/安全/性能/测试/回归）
- grill_me: 追问式设计评审（在让 AI 实施前盘问设计漏洞）
- stop_slop: 去 AI 味检测清理（识别套话/空话/过分强调）

设计原则（对齐 llm-first-loop 既有模式）:
- 工具定义 _TOOL_DEF + run_xxx 函数（独立可测）
- 通过 corrections.py 注册到工具列表
- 不引入新依赖（仅标准库 + 现有 LLM 客户端）
"""

from __future__ import annotations

import re
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus


# ════════════════════════════════════════════════════════════════════════
# Skill 1: code_review — 多维代码审查
# ════════════════════════════════════════════════════════════════════════

CODE_REVIEW_TOOL_DEF: dict = {
    "name": "code_review",
    "description": "多维代码审查工具（5维：正确性/安全/性能/测试/回归）。何时用: 实施完一段代码想自查/发现代码异味/提交前自查。何时不用: 仅查架构状态用 architecture_status；评估整个项目用 self_evaluate。失败对策: 无代码可审时如实返回空审查报告，不伪造审查结果。",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "待审代码片段"},
            "language": {"type": "string", "description": "代码语言（python/go/typescript等，默认python）"},
            "focus": {"type": "array", "items": {"type": "string"}, "description": "审查重点维度（默认全5维：correctness/security/performance/test/regression）"},
        },
        "required": ["code"],
    },
}

# 审查维度模板（启发式检查清单）
_REVIEW_CHECKLIST = {
    "correctness": [
        "边界条件（空/null/0/负数/超长）",
        "异常路径（错误是否被吞掉）",
        "类型匹配（隐式转换风险）",
        "并发/异步安全（race condition）",
    ],
    "security": [
        "输入校验（SQL注入/XSS/命令注入）",
        "敏感信息泄露（密码/token/密钥硬编码）",
        "权限校验（越权访问）",
        "日志安全（不打印敏感数据）",
    ],
    "performance": [
        "算法复杂度（O(n^2) → O(n) 可优化点）",
        "重复计算（可缓存热点）",
        "IO 密集（同步阻塞 → 异步）",
        "内存占用（大对象/累积泄漏）",
    ],
    "test": [
        "可测性（依赖是否可注入/隔离）",
        "断言覆盖（正常+异常路径）",
        "边界用例（空/极值）",
        "Mock 友好（外部依赖可替换）",
    ],
    "regression": [
        "向后兼容（旧 API 是否被破坏）",
        "数据库迁移（schema 变更是否安全）",
        "配置变更（默认值是否破坏旧部署）",
        "调用方影响（是否引入强制依赖）",
    ],
}

_DEFAULT_FOCUS = ["correctness", "security", "performance", "test", "regression"]

_CODE_SMELLS = [
    (r"\beval\(", "使用 eval()，安全风险"),
    (r"\bexec\(", "使用 exec()，安全风险"),
    (r"password\s*=\s*['\"]", "疑似密码硬编码"),
    (r"\btodo\b", "存在未完成标记"),
    (r"\bfixme\b", "存在 FIXME 待修复"),
    (r"\bprint\(", "调试 print 未清理"),
    (r"\bpass\s*#\s*implement", "空 pass 占位未实现"),
]


def run_code_review(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """code_review: 多维代码审查（启发式检查清单 + 代码异味扫描）.

    限制: 启发式而非 LLM 深度审查，但可在 LLM 调用前/后做轻量自查.
    深度审查仍需 LLM 阅读代码 + 上下文理解.
    """
    code = str(args.get("code", "")).strip()
    language = str(args.get("language", "python")).strip() or "python"
    focus = args.get("focus") or _DEFAULT_FOCUS
    if not isinstance(focus, list):
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: focus 需为数组。原因: focus 应为字符串列表（correctness/security/performance/test/regression）。建议: 提供 focus=['correctness', 'security'] 或省略使用全5维。",
            tool_call_id="", tool_name="code_review",
        )
    if not code:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: code 为空。原因: code 必填。建议: 提供待审代码字符串。",
            tool_call_id="", tool_name="code_review",
        )

    lines = code.splitlines()
    findings: list[dict] = []

    # 1. 维度清单（提示 LLM 阅读时重点关注）
    dim_section = ["## 📋 审查维度清单", ""]
    for dim in focus:
        if dim in _REVIEW_CHECKLIST:
            dim_section.append(f"### {dim}")
            for item in _REVIEW_CHECKLIST[dim]:
                dim_section.append(f"- {item}")
            dim_section.append("")

    # 2. 代码异味扫描（启发式）
    smell_section = ["## 🔍 代码异味扫描（启发式）", ""]
    smells_found = False
    for pattern, desc in _CODE_SMELLS:
        if re.search(pattern, code, re.IGNORECASE):
            smell_section.append(f"- ⚠️  {desc}")
            smells_found = True
    if not smells_found:
        smell_section.append("- ✅ 未发现常见代码异味")

    # 3. 基础统计
    stat_section = [
        "## 📊 基础统计",
        f"- 行数: {len(lines)}",
        f"- 非空行: {sum(1 for l in lines if l.strip())}",
        f"- 注释行: {sum(1 for l in lines if l.strip().startswith(('#', '//', '/*', '--'))) }",
        f"- 缩进风格: {'空格' if any(l.startswith(' ') for l in lines) else 'Tab/无'}",
        f"- 语言: {language}",
        "",
    ]

    # 4. 提醒：深度审查需 LLM 阅读
    deep_review_hint = (
        "## 💡 深度审查建议\n\n"
        "本工具为**启发式轻量自查**，提供维度清单 + 常见异味扫描。\n"
        "深度审查（业务逻辑/算法正确性/复杂场景）需 LLM 阅读完整代码 + 项目上下文。\n"
        "建议流程: ① 本工具快扫 → ② LLM 阅读审查 → ③ 修复 → ④ 重跑本工具验证。\n"
    )

    report = "\n".join(
        ["# 🔍 code_review 审查报告", ""]
        + stat_section
        + dim_section
        + smell_section
        + ["", deep_review_hint]
    )

    findings_summary = f"[code_review] 完成 {language} 审查 {len(lines)} 行, 异味扫描={smells_found}, 维度={len(focus)}"
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=report,
        tool_call_id="",
        tool_name="code_review",
    )


# ════════════════════════════════════════════════════════════════════════
# Skill 2: grill_me — 追问式设计评审
# ════════════════════════════════════════════════════════════════════════

GRILL_ME_TOOL_DEF: dict = {
    "name": "grill_me",
    "description": "追问式设计评审（在让 AI 实施前盘问设计漏洞）。何时用: 准备实施一个方案/特性/重构前，主动触发深度盘问找出未思考到的边界。何时不用: 任务简单无需盘问；已确认方案要落地时（应直接做）。失败对策: 设计为空时如实返回错误。",
    "parameters": {
        "type": "object",
        "properties": {
            "design": {"type": "string", "description": "当前设计/方案描述（可粗略，AI 会追问补全）"},
            "depth": {"type": "integer", "description": "追问深度（1-5，默认3，每层 4-6 个问题）"},
            "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "重点追问领域（default: edge_cases/failure_modes/scale/security/ux）"},
        },
        "required": ["design"],
    },
}

_GRILL_QUESTIONS = {
    "edge_cases": [
        "如果输入为空/null/0/超长字符串，行为是什么？",
        "如果系统时钟/网络/磁盘满，行为是什么？",
        "如果同一操作并发执行 100 次，行为是什么？",
        "如果用户身份/权限缺失，行为是什么？",
        "如果配置/依赖版本不一致，行为是什么？",
    ],
    "failure_modes": [
        "最坏失败场景是什么？数据会丢失/损坏吗？",
        "失败是可恢复的还是灾难性的？有无降级方案？",
        "失败如何被检测（日志/指标/告警）？",
        "失败重试策略是否合理（指数退避/最大次数/幂等性）？",
        "失败信息是否对用户友好（不暴露内部堆栈）？",
    ],
    "scale": [
        "当数据量增长 1000 倍时，哪些组件先成瓶颈？",
        "是否有热路径/冷路径区分？冷路径可异步吗？",
        "缓存策略是什么？缓存失效时如何保护后端？",
        "状态是否需要持久化？持久化方案能扛住崩溃吗？",
    ],
    "security": [
        "输入是否可信？是否需要校验/转义？",
        "敏感数据如何处理（日志/存储/传输）？",
        "权限边界在哪里？谁能调用/谁能读/谁能改？",
        "有无可被滥用的入口（自动化脚本/重放攻击）？",
    ],
    "ux": [
        "用户首次接触能否 30 秒内理解价值？",
        "错误信息能否帮用户自助修复？",
        "有无可观察/可调试入口（让用户看见内部状态）？",
        "是否符合用户已有心智模型（不学新概念）？",
    ],
}


def run_grill_me(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """grill_me: 追问式设计评审.

    流程: 用户给设计 → 工具按 depth 层数每层 4-6 个问题追问 → 用户回答
    → 工具汇总盲点 → 用户据此修订设计.
    """
    design = str(args.get("design", "")).strip()
    if not design:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: design 为空。原因: 需提供设计描述。建议: 哪怕一句话也可，AI 会追问补全。",
            tool_call_id="", tool_name="grill_me",
        )

    depth = max(1, min(int(args.get("depth", 3) or 3), 5))
    focus_areas = args.get("focus_areas") or list(_GRILL_QUESTIONS.keys())
    if not isinstance(focus_areas, list):
        focus_areas = list(_GRILL_QUESTIONS.keys())

    lines = ["# 🔥 grill_me 追问式设计评审", ""]
    lines.append(f"**当前设计** ({len(design)} 字符):")
    lines.append("```")
    lines.append(design[:500] + ("..." if len(design) > 500 else ""))
    lines.append("```")
    lines.append("")
    lines.append(f"**追问深度**: {depth} 层")
    lines.append(f"**重点领域**: {', '.join(focus_areas)}")
    lines.append("")

    # 第一层：必问问题
    lines.append("## 🎯 第一层（必问，覆盖全领域）")
    lines.append("")
    for area in focus_areas:
        if area in _GRILL_QUESTIONS:
            lines.append(f"### {area}")
            for q in _GRILL_QUESTIONS[area]:
                lines.append(f"- {q}")
            lines.append("")

    # 后续层：递进问题（提示用户想更深）
    for layer in range(2, depth + 1):
        lines.append(f"## 🔁 第 {layer} 层（递进追问）")
        lines.append("")
        lines.append(f"- 第 {layer} 层问题基于您对前 {layer-1} 层的回答自动生成")
        lines.append("- 回答前一层的每条问题后，再说'继续 grill' 触发下一层")
        lines.append("- 或直接说'够了'终止追问")
        lines.append("")

    lines.append("## 💡 使用方式")
    lines.append("")
    lines.append("1. **逐条回答上述问题**（可长可短）")
    lines.append("2. 回答中如发现新盲点，写在末尾的'新盲点'小节")
    lines.append("3. 回答完整后 AI 会汇总盲点 → 您据此修订设计")
    lines.append("4. 设计修订后再 grill_me 一次（覆盖之前的盲点）")
    lines.append("")
    lines.append("## ⚠️ 注意")
    lines.append("")
    lines.append("- grill_me 是**强制盘问模式**，问题必须回答（不能说'略过'）")
    lines.append("- 每个问题至少一句话（含'我考虑了 X，理由是 Y' 或'暂未考虑，需补充'）")
    lines.append("- 跳过 = 假装设计完整 = 上线后被坑")

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="\n".join(lines),
        tool_call_id="",
        tool_name="grill_me",
    )


# ════════════════════════════════════════════════════════════════════════
# Skill 3: stop_slop — 去 AI 味检测清理
# ════════════════════════════════════════════════════════════════════════

STOP_SLOP_TOOL_DEF: dict = {
    "name": "stop_slop",
    "description": "去 AI 味检测清理（识别套话/空话/过分强调/虚假精确）。何时用: AI 输出看起来'正确但读起来别扭'时自查；给客户/老板前清洗文本。何时不用: 内部技术对话；纯事实陈述。失败对策: 文本为空时如实返回错误。",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "待清洗文本"},
            "aggressive": {"type": "boolean", "description": "激进模式（删除 vs 仅标记，默认false=仅标记）"},
        },
        "required": ["text"],
    },
}

_SLOP_PATTERNS = [
    (r"不仅仅是[^，。]*，更是[^。]*", "✂️  '不仅仅是 X，更是 Y' 双重强调套话"),
    (r"首先[，,]然后[，,]最后[，,][^。]*", "✂️  '首先...然后...最后...' 模板化叙述"),
    (r"至关重要?的是", "✂️  '至关重要' 过分强调"),
    (r"在[^，。]{2,15}方面[，,]", "✂️  '在 X 方面' 学术腔"),
    (r"总而言之[，,]", "✂️  '总而言之' 陈词滥调"),
    (r"综上所述[，,]", "✂️  '综上所述' 陈词滥调"),
    (r"具有重要(?:的)?意义", "✂️  '具有重要意义' 套话"),
    (r"扮演着?重要(?:的)?角色", "✂️  '扮演重要角色' 套话"),
    (r"让我们[一齐]?[一齐]?[来]?[^，。]*", "✂️  '让我们一起' 课堂腔"),
    (r"\\b(?:very|really|extremely|absolutely)\\b", "✂️  英文过分强调副词"),
    (r"\\b(?:it is important to note that)\\b", "✂️  'it is important to note that' 学术腔"),
    (r"\\b(?:it should be noted that)\\b", "✂️  'it should be noted that' 学术腔"),
    (r"\d+%\s*的?(?:准确率|成功率|可能性)", "✂️  模糊百分比（数字幻觉）"),
]


def run_stop_slop(ctx: Any, audit: Any, args: dict) -> ToolResult:
    """stop_slop: 去 AI 味检测清理.

    aggressive=false: 仅标记 slop 段落，输出位置+原因
    aggressive=true: 直接替换为简短版本（需 LLM 二次加工）.
    """
    text = str(args.get("text", "")).strip()
    if not text:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 事实: text 为空。原因: 需提供待清洗文本。",
            tool_call_id="", tool_name="stop_slop",
        )
    aggressive = bool(args.get("aggressive", False))

    lines = ["# 🧹 stop_slop 去 AI 味检测报告", ""]
    lines.append(f"**原文本**: {len(text)} 字符")
    lines.append(f"**模式**: {'激进替换' if aggressive else '仅标记'}")
    lines.append("")

    issues: list[dict] = []
    cleaned = text
    for pattern, desc in _SLOP_PATTERNS:
        matches = list(re.finditer(pattern, cleaned, re.IGNORECASE | re.MULTILINE))
        for m in matches:
            issues.append({
                "pattern": desc,
                "matched": m.group(0)[:50] + ("..." if len(m.group(0)) > 50 else ""),
                "start": m.start(),
                "end": m.end(),
            })
        if aggressive and matches:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

    if not issues:
        lines.append("✅ 未发现典型 AI 味")
    else:
        lines.append(f"## ⚠️ 发现 {len(issues)} 处 AI 味\n")
        for i, iss in enumerate(issues, 1):
            lines.append(f"### 第 {i} 处")
            lines.append(f"- **类型**: {iss['pattern']}")
            lines.append(f"- **原文片段**: `{iss['matched']}`")
            lines.append(f"- **位置**: {iss['start']}-{iss['end']}")
            lines.append("")

    if aggressive:
        # 清理多余空白
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # 清理多余标点
        cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
        cleaned = re.sub(r"。。", "。", cleaned)
        lines.append("## 📝 清洗后文本（激进模式）")
        lines.append("```")
        lines.append(cleaned)
        lines.append("```")
        lines.append("")
        lines.append("⚠️  激进替换会丢失语义，请人工二次润色")
    else:
        lines.append("## 💡 建议处理")
        lines.append("")
        lines.append("- 每处标记的 AI 味用具体事实/数字/例子替换")
        lines.append("- 删除双重强调（'不仅仅 X，更是 Y' → 直接说 Y）")
        lines.append("- 删除课堂腔/学术腔（'首先...然后...最后' → 直接陈述）")
        lines.append("- 删除模糊百分比（'90% 的成功率' → 给出测量依据）")

    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="\n".join(lines),
        tool_call_id="",
        tool_name="stop_slop",
    )
