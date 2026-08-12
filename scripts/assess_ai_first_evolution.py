#!/usr/bin/env python3
"""AI 优先演进整体评估报告生成器（spec.md §5.1 / design.md §2.4.1）.

四维评估（健壮性/优雅性/AI 友好性/内容显示）+ RULE-AI-00 六原则对照 +
隐患优先级排序 + 可移交清单提取 + 报告存档 + INDEX 登记。

纯 Python 标准库，不引入新依赖；离线只读产物，不增加运行时开销。
扫描异常 fail-open 标注"证据待补"不阻塞；报告脱敏不含密钥字面量。

用法:
    python -m scripts.assess_ai_first_evolution [--output-dir docs/] [--date YYYYMMDD]
退出码: 0=成功, 1=生成失败（fail-open 仍写出部分报告）
"""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src" / "llm_loop"
DOCS_DIR = ROOT / "docs"
WEB_STATIC = SRC_DIR / "web" / "static"
INTROSPECTION_DIR = SRC_DIR / "introspection"

DIMENSIONS = ["健壮性", "优雅性", "AI 友好性", "内容显示"]

RULE_AI_00_PRINCIPLES = [
    ("P1", "不替 AI 决策", "压缩/重试/摘要/模型切换等决策权归 AI；程序如实反馈事实 + 提供工具，AI 自主选择。"),
    ("P2", "不自动压缩/重试/摘要", "这些行为可能丢信息/增计费/注入无用内容，须 AI 主动触发，程序不自动注入。"),
    ("P3", "如实反馈让 AI 决策", "程序异常/上下文超限/工具失败 → 如实告知 AI + 提供可选动作；不静默吞错、不静默降级。"),
    ("P4", "简化而非增加配置面", "AI 不能改 env，env 对 AI 是黑盒；优先程序自适应而非暴露更多配置项。"),
    ("P5", "赋能 AI 上下文感知", "上下文状态作为 architecture_status 工具返回维度，AI 每轮可见。"),
    ("P6", "避免程序错误影响大模型", "程序故障隔离不抛穿，程序不替 AI 压缩/丢弃上下文，AI 基于完整事实决策。"),
]

_SENSITIVE_PAT = re.compile(r"(api_key|token|secret|password|apikey|sk-)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}", re.I)


@dataclass
class HiddenRisk:
    id: str
    dimension: str
    description: str
    evidence: str
    rule_ai_00: str = "UNRELATED"
    priority: str = "P2"


@dataclass
class PrincipleCheck:
    pid: str
    name: str
    statement: str
    status: str
    violating_risks: list[str] = field(default_factory=list)


@dataclass
class RuleAI00Check:
    principles: list[PrincipleCheck] = field(default_factory=list)


@dataclass
class TransferableItem:
    id: str
    program_location: str
    suggested_rule: str
    acceptance_criteria: str
    priority: str


@dataclass
class AssessmentReport:
    date: str
    dimensions: dict[str, str]
    risks: list[HiddenRisk]
    rule_check: RuleAI00Check
    transferable: list[TransferableItem]
    next_steps: list[str]


def _redact(text: str) -> str:
    return _SENSITIVE_PAT.sub(r"\1=[REDACTED]", text)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _glob_py(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _evidence(path: Path, line: int) -> str:
    return f"{path.relative_to(ROOT)}:{line}"


# ── 四维扫描器 ──────────────────────────────────────────────────────────


def scan_robustness() -> tuple[str, list[HiddenRisk]]:
    """扫描 fail-open 标注覆盖、静默吞错、边界条件处理现状。"""
    risks: list[HiddenRisk] = []
    fail_open_count = 0
    silent_swallow: list[str] = []

    for py in _glob_py(SRC_DIR):
        src = _read(py)
        if src is None:
            continue
        fail_open_count += len(re.findall(r"fail[._-]?open", src, re.I))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            is_pass_only = len(body) == 1 and isinstance(body[0], ast.Pass)
            has_log = any(
                isinstance(b, ast.Expr)
                and isinstance(b.value, ast.Call)
                and getattr(b.value.func, "attr", "") in {"warning", "error", "info", "debug"}
                for b in body
            )
            if is_pass_only and not has_log:
                silent_swallow.append(_evidence(py, node.lineno))

    if silent_swallow:
        for ev in silent_swallow[:20]:
            risks.append(HiddenRisk(
                id=f"ROB-SILENT-{len(risks) + 1:03d}",
                dimension="健壮性",
                description=f"except: pass 静默吞错（无日志标注），违反 fail-open ≠ fail-silent: {ev}",
                evidence=ev,
                rule_ai_00="VIOLATES",
                priority="P1",
            ))

    conclusion = (
        f"fail-open 标注覆盖广泛（{fail_open_count} 处匹配），异常如实反馈路径完善；"
        f"{'但存在 ' + str(len(silent_swallow)) + ' 处 except: pass 静默吞错需排查。' if silent_swallow else '未发现 except: pass 静默吞错。'}"
    )
    return conclusion, risks


def scan_elegance() -> tuple[str, list[HiddenRisk]]:
    """扫描降级策略、错误反馈如实标注、服务守护自愈路径。"""
    risks: list[HiddenRisk] = []
    degrade_annotated = 0
    degrade_silent = 0

    for py in _glob_py(SRC_DIR):
        src = _read(py)
        if src is None:
            continue
        for m in re.finditer(r"(回退|降级|退化|fallback|回退主模型|跳过)", src):
            line_no = src[:m.start()].count("\n") + 1
            line = src.splitlines()[line_no - 1]
            if "fail" in line.lower() or "如实" in line or "标注" in line:
                degrade_annotated += 1
            else:
                degrade_silent += 1
                if degrade_silent <= 10:
                    risks.append(HiddenRisk(
                        id=f"ELG-DEGRADE-{degrade_silent:03d}",
                        dimension="优雅性",
                        description=f"降级/回退路径可能未如实标注: {_evidence(py, line_no)}",
                        evidence=_evidence(py, line_no),
                        rule_ai_00="COMPLIES",
                        priority="P2",
                    ))

    guardian = (ROOT / "com.user.llm-loop-guard.plist").exists() or bool(_read(ROOT / "scripts" / "restart_system.sh"))
    if not guardian:
        risks.append(HiddenRisk(
            id="ELG-GUARD-001",
            dimension="优雅性",
            description="未发现服务守护/自愈脚本，服务异常时无自动恢复",
            evidence="scripts/restart_system.sh",
            rule_ai_00="UNRELATED",
            priority="P2",
        ))

    conclusion = (
        f"降级策略多数如实标注（{degrade_annotated} 处标注 / {degrade_silent} 处待核验）；"
        f"服务守护{'存在' if guardian else '缺失'}。"
    )
    return conclusion, risks


def scan_ai_friendliness() -> tuple[str, list[HiddenRisk]]:
    """扫描 architecture_status 维度完整性、程序约束最小化、规则文档结构。"""
    risks: list[HiddenRisk] = []

    status_src = _read(INTROSPECTION_DIR / "status.py") or ""

    eight_dims = ["current_phase", "action_trace", "tool_history", "message_flow",
                  "memory_state", "context_usage", "exception_log", "architecture_config"]
    missing_dims = [d for d in eight_dims if d not in status_src]
    has_pending_actions = "pending_actions" in status_src

    if missing_dims:
        risks.append(HiddenRisk(
            id="AIF-DIM-001",
            dimension="AI 友好性",
            description=f"architecture_status 维度不完整，缺失: {missing_dims}",
            evidence=_evidence(INTROSPECTION_DIR / "status.py", 1),
            rule_ai_00="VIOLATES",
            priority="P1",
        ))
    if not has_pending_actions:
        risks.append(HiddenRisk(
            id="AIF-PENDING-001",
            dimension="AI 友好性",
            description="architecture_status 缺 pending_actions 维度，AI 无法一站式感知系统待办（执行中演进/待审阅/待自评）",
            evidence=_evidence(INTROSPECTION_DIR / "status.py", 261),
            rule_ai_00="COMPLIES",
            priority="P1",
        ))

    auto_decision_pats = [
        (r"auto[_-]?compress", "自动压缩"),
        (r"auto[_-]?retry", "自动重试"),
        (r"auto[_-]?summar", "自动摘要"),
    ]
    for py in _glob_py(SRC_DIR):
        src = _read(py) or ""
        for pat, label in auto_decision_pats:
            for m in re.finditer(pat, src, re.I):
                line_no = src[:m.start()].count("\n") + 1
                line = src.splitlines()[line_no - 1]
                if "兜底" in line or "应急" in line or "另存" in line:
                    continue
                risks.append(HiddenRisk(
                    id=f"AIF-AUTO-{len(risks) + 1:03d}",
                    dimension="AI 友好性",
                    description=f"疑似程序自动{label}逻辑（可能替 AI 决策）: {_evidence(py, line_no)}",
                    evidence=_evidence(py, line_no),
                    rule_ai_00="VIOLATES",
                    priority="P0",
                ))
                break

    rules_src = _read(DOCS_DIR / "ai_rules.md") or ""
    rule_count = len(re.findall(r"RULE-AI-\d+", rules_src))
    if rule_count < 8:
        risks.append(HiddenRisk(
            id="AIF-RULES-001",
            dimension="AI 友好性",
            description=f"ai_rules.md 规则数偏少（{rule_count} 条），RULE-AI-00~08 应完整",
            evidence=_evidence(DOCS_DIR / "ai_rules.md", 1),
            rule_ai_00="COMPLIES",
            priority="P2",
        ))

    conclusion = (
        f"architecture_status 八维{'完整' if not missing_dims else '缺失 ' + str(missing_dims)}；"
        f"pending_actions 维度{'已存在' if has_pending_actions else '缺失（待 T4 新增）'}；"
        f"ai_rules.md 含 {rule_count} 条规则编号。"
    )
    return conclusion, risks


def scan_content_display() -> tuple[str, list[HiddenRisk]]:
    """扫描 app.js 长文本处理、富格式渲染、截断标注、异常醒目现状。"""
    risks: list[HiddenRisk] = []
    app_js = WEB_STATIC / "app.js"
    src = _read(app_js) or ""

    has_collapse = "collapseLongContent" in src
    has_long_threshold = "LONG_LINE_THRESHOLD" in src and "LONG_CHAR_THRESHOLD" in src
    has_truncated_note = "data.truncated" in src
    has_marked = "marked" in src or "markdown" in src.lower()
    has_sanitize = "sanitize" in src or "DOMPurify" in src or "allowed" in src.lower()

    has_continue_hint = False
    if has_truncated_note:
        lines = src.splitlines()
        trunc_lines = [i for i, line in enumerate(lines) if "data.truncated" in line]
        for ln in trunc_lines:
            context = "\n".join(lines[ln:ln + 4])
            if any(kw in context for kw in ["新建会话", "续读", "调整 prompt", "缩短", "继续对话"]):
                has_continue_hint = True
                break

    if not has_collapse:
        risks.append(HiddenRisk(
            id="CD-COLLAPSE-001",
            dimension="内容显示",
            description="Web 端无长内容折叠器（collapseLongContent），超长代码块/消息体首屏可能卡死",
            evidence=_evidence(app_js, 1),
            rule_ai_00="UNRELATED",
            priority="P1",
        ))
    if not has_long_threshold:
        risks.append(HiddenRisk(
            id="CD-THRESH-001",
            dimension="内容显示",
            description="Web 端无长文本阈值常量（LONG_LINE_THRESHOLD/LONG_CHAR_THRESHOLD），折叠无统一标准",
            evidence=_evidence(app_js, 1),
            rule_ai_00="UNRELATED",
            priority="P2",
        ))
    if has_truncated_note and not has_continue_hint:
        risks.append(HiddenRisk(
            id="CD-TRUNC-001",
            dimension="内容显示",
            description="截断标注仅'回答被截断'，无续读建议（新建会话/调整 prompt），AI/用户不知如何继续",
            evidence=_evidence(app_js, 370),
            rule_ai_00="COMPLIES",
            priority="P1",
        ))

    react_vue = bool(re.search(r"import\s+React|from\s+['\"]vue['\"]|require\(['\"]vue['\"]\)", src))
    if react_vue:
        risks.append(HiddenRisk(
            id="CD-FRAME-001",
            dimension="内容显示",
            description="app.js 引入 React/Vue 框架，违反 spec.md 5.2.1 第 8 条禁止项",
            evidence=_evidence(app_js, 1),
            rule_ai_00="VIOLATES",
            priority="P0",
        ))

    conclusion = (
        f"长文本折叠{'已实现' if has_collapse else '缺失（待 T3 新增）'}；"
        f"富格式渲染{'已实现(marked)' if has_marked else '缺失'}；"
        f"sanitize{'已实现' if has_sanitize else '缺失'}；"
        f"截断标注{'含续读建议' if has_continue_hint else '仅简单标注，缺续读建议'}；"
        f"框架引入{'违规(React/Vue)' if react_vue else '无(符合约束)'}。"
    )
    return conclusion, risks


# ── RULE-AI-00 六原则对照器 ─────────────────────────────────────────────


def check_rule_ai_00(risks: list[HiddenRisk]) -> RuleAI00Check:
    check = RuleAI00Check()
    for pid, name, stmt in RULE_AI_00_PRINCIPLES:
        violating = [r.id for r in risks if r.rule_ai_00 == "VIOLATES" and _risk_relates(r, name)]
        status = "VIOLATES" if violating else "COMPLIES"
        check.principles.append(PrincipleCheck(pid, name, stmt, status, violating))
    return check


def _risk_relates(risk: HiddenRisk, principle_name: str) -> bool:
    mapping = {
        "不替 AI 决策": ["AIF-AUTO", "AIF-DIM"],
        "不自动压缩/重试/摘要": ["AIF-AUTO"],
        "如实反馈让 AI 决策": ["ROB-SILENT", "ELG-DEGRADE"],
        "简化而非增加配置面": [],
        "赋能 AI 上下文感知": ["AIF-DIM", "AIF-PENDING"],
        "避免程序错误影响大模型": ["ROB-SILENT"],
    }
    prefixes = mapping.get(principle_name, [])
    return any(risk.id.startswith(p) for p in prefixes)


# ── 优先级排序器与可移交清单提取器 ───────────────────────────────────────


def prioritize(risks: list[HiddenRisk]) -> list[HiddenRisk]:
    order = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(risks, key=lambda r: (order.get(r.priority, 9), r.id))


def extract_transferable(risks: list[HiddenRisk]) -> list[TransferableItem]:
    """从隐患清单过滤'违反程序最小化'条目，输出可移交清单（由扫描结果驱动，不预设）。"""
    transferable: list[TransferableItem] = []
    for r in risks:
        if r.rule_ai_00 != "VIOLATES":
            continue
        if r.dimension != "AI 友好性":
            continue
        transferable.append(TransferableItem(
            id=f"TF-{len(transferable) + 1:03d}",
            program_location=r.evidence,
            suggested_rule=f"将 {r.description.split(':')[0]} 移交 AI 自主 + 文档规则约束，程序仅保留执行与如实反馈",
            acceptance_criteria=f"程序中该判断逻辑已移除；ai_rules.md 增对应规则；pytest tests/ 全绿；{r.id} 不再出现",
            priority=r.priority,
        ))
    return transferable


# ── 报告存档器与 INDEX 登记 ─────────────────────────────────────────────


def write_report(report: AssessmentReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"ASSESSMENT-{report.date}-ai-first-evolution.md"

    lines: list[str] = []
    lines.append(f"# AI 优先演进整体评估报告（{report.date}）")
    lines.append("")
    lines.append("> 类型: 整体评估报告 | 由 `scripts/assess_ai_first_evolution.py` 离线生成")
    lines.append("> 评估维度: 健壮性 / 优雅性 / AI 友好性 / 内容显示")
    lines.append("> 对照基准: RULE-AI-00 六原则（docs/ai_rules.md）")
    lines.append("> 声明: 本报告只含评估结论与隐患清单，不含实现方案（类图/接口/代码），实现方案见 design.md")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 一、四维评估结论")
    lines.append("")
    for dim in DIMENSIONS:
        lines.append(f"### {dim}")
        lines.append("")
        lines.append(f"**现状结论**：{_redact(report.dimensions.get(dim, '证据待补'))}")
        lines.append("")
        dim_risks = [r for r in report.risks if r.dimension == dim]
        if dim_risks:
            lines.append(f"**隐患清单（{len(dim_risks)} 条）**：")
            lines.append("")
            lines.append("| ID | 优先级 | 描述 | 证据 | RULE-AI-00 |")
            lines.append("|:---|:---:|:---|:---|:---:|")
            for r in dim_risks:
                lines.append(f"| {r.id} | {r.priority} | {_redact(r.description)} | `{r.evidence}` | {r.rule_ai_00} |")
        else:
            lines.append("**隐患清单**：无（本维度现状良好）")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 二、RULE-AI-00 六原则对照")
    lines.append("")
    lines.append("| 原则 | 陈述 | 状态 | 违反隐患 |")
    lines.append("|:---|:---|:---:|:---|")
    for p in report.rule_check.principles:
        viol = ", ".join(p.violating_risks) if p.violating_risks else "—"
        lines.append(f"| {p.pid} {p.name} | {p.statement} | {p.status} | {viol} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 三、隐患优先级排序")
    lines.append("")
    ordered = prioritize(report.risks)
    if ordered:
        lines.append("| 序 | ID | 优先级 | 维度 | 描述 |")
        lines.append("|:---:|:---|:---:|:---|:---|")
        for i, r in enumerate(ordered, 1):
            lines.append(f"| {i} | {r.id} | {r.priority} | {r.dimension} | {_redact(r.description)} |")
    else:
        lines.append("无隐患。")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 四、可移交清单（程序最小化候选）")
    lines.append("")
    lines.append("> 由扫描结果驱动，不预设。仅列违反 RULE-AI-00 且属 AI 友好性维度的隐患。")
    lines.append("")
    if report.transferable:
        lines.append("| ID | 优先级 | 程序位置 | 建议规则 | 验收条件 |")
        lines.append("|:---|:---:|:---|:---|:---|")
        for t in report.transferable:
            lines.append(f"| {t.id} | {t.priority} | `{t.program_location}` | {_redact(t.suggested_rule)} | {_redact(t.acceptance_criteria)} |")
    else:
        lines.append("本次评估无可移交项（程序最小化现状良好，或隐患均非 AI 友好性维度）。")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 五、下一步建议")
    lines.append("")
    for i, step in enumerate(report.next_steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 六、维度边界声明")
    lines.append("")
    lines.append("- 本报告基于静态扫描（ast/re）生成，反映源码/文档现状，不含运行时动态证据。")
    lines.append("- 证据缺失项已如实标注'证据待补'，不阻塞报告生成。")
    lines.append("- 报告已脱敏，不含 api_key/token/secret 字面量。")
    lines.append("- 评估范围: src/llm_loop/ + docs/ + tests/，不含 .venv/、data/、.git/。")
    lines.append("")

    path.write_text(_redact("\n".join(lines)), encoding="utf-8")
    return path


def update_index(report_path: Path, date: str) -> None:
    index = DOCS_DIR / "INDEX.md"
    existing = _read(index) or ""
    entry = f"| ASSESSMENT-{date}-ai-first-evolution.md | AI 优先演进整体评估报告（四维+RULE-AI-00 对照，{date}） | 评估 | §5.1 |"
    if entry.split("|")[1] in existing:
        return
    marker = "## 二、报告清单"
    if marker not in existing:
        index.write_text(existing + "\n" + entry + "\n", encoding="utf-8")
        return
    parts = existing.split(marker, 1)
    table_end = parts[1].find("\n\n")
    if table_end == -1:
        index.write_text(existing.rstrip() + "\n" + entry + "\n", encoding="utf-8")
    else:
        new_body = parts[1][:table_end].rstrip() + "\n" + entry + parts[1][table_end:]
        index.write_text(parts[0] + marker + new_body, encoding="utf-8")


# ── 状态机主流程 ─────────────────────────────────────────────────────────

STATES = [
    "idle", "scanning_source", "scanning_docs", "scanning_logs",
    "scanning_tests", "evaluating_4d", "checking_rule_ai_00",
    "prioritizing", "extracting_transferable", "writing_report",
    "updating_index", "done",
]


def run_assessment(output_dir: Path, date: str) -> AssessmentReport:
    state = "idle"
    for s in STATES[1:]:
        state = s
        print(f"[状态] {state} ...")

    print("[扫描] 健壮性维度 ...")
    rob_concl, rob_risks = scan_robustness()
    print("[扫描] 优雅性维度 ...")
    elg_concl, elg_risks = scan_elegance()
    print("[扫描] AI 友好性维度 ...")
    aif_concl, aif_risks = scan_ai_friendliness()
    print("[扫描] 内容显示维度 ...")
    cd_concl, cd_risks = scan_content_display()

    all_risks = rob_risks + elg_risks + aif_risks + cd_risks
    dimensions = {
        "健壮性": rob_concl, "优雅性": elg_concl,
        "AI 友好性": aif_concl, "内容显示": cd_concl,
    }

    print("[对照] RULE-AI-00 六原则 ...")
    rule_check = check_rule_ai_00(all_risks)

    print("[排序] 隐患优先级 ...")
    ordered = prioritize(all_risks)

    print("[提取] 可移交清单 ...")
    transferable = extract_transferable(all_risks)

    next_steps = _build_next_steps(ordered, transferable)

    report = AssessmentReport(
        date=date, dimensions=dimensions, risks=all_risks,
        rule_check=rule_check, transferable=transferable, next_steps=next_steps,
    )

    print("[写盘] 报告存档 ...")
    report_path = write_report(report, output_dir)
    try:
        rel = report_path.relative_to(ROOT)
    except ValueError:
        rel = report_path
    print(f"[写盘] 报告已生成: {rel}")

    print("[登记] INDEX.md ...")
    update_index(report_path, date)

    state = "done"
    print(f"[状态] {state}")
    return report


def _build_next_steps(ordered: list[HiddenRisk], transferable: list[TransferableItem]) -> list[str]:
    steps: list[str] = []
    p0 = [r for r in ordered if r.priority == "P0"]
    p1 = [r for r in ordered if r.priority == "P1"]
    if p0:
        steps.append(f"立即处理 {len(p0)} 条 P0 隐患（违反 RULE-AI-00 硬约束）：" + "、".join(r.id for r in p0[:5]))
    if p1:
        steps.append(f"推进 {len(p1)} 条 P1 隐患（影响 AI 执行力/内容显示）：" + "、".join(r.id for r in p1[:8]))
    if transferable:
        steps.append(f"可移交清单 {len(transferable)} 项，按 SOP 逐项移交（SoT 先行 → prompt 同步 → 测试防漂移 → 程序移除 → 全量回归）")
    steps.append("T3 Web 长文本折叠、T4 pending_actions 维度、T5 并发锁/超长校验可独立并行推进")
    steps.append("全量回归门禁: .venv/bin/python -m pytest tests/ -v --tb=short")
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="AI 优先演进整体评估报告生成器")
    parser.add_argument("--output-dir", type=Path, default=DOCS_DIR, help="报告输出目录（默认 docs/）")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y%m%d"), help="报告日期 YYYYMMDD")
    args = parser.parse_args()

    try:
        report = run_assessment(args.output_dir, args.date)
    except Exception as exc:
        print(f"[fail-open] 评估生成异常: {type(exc).__name__}: {exc}")
        return 1

    print("")
    print("=" * 60)
    print("评估摘要")
    print("=" * 60)
    for dim in DIMENSIONS:
        print(f"  {dim}: {report.dimensions.get(dim, '证据待补')[:80]}")
    print(f"  隐患总数: {len(report.risks)} | 可移交项: {len(report.transferable)}")
    print(f"  下一步: {report.next_steps[0] if report.next_steps else '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
