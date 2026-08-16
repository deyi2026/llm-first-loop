"""六路径数据模型（design.md §2.3，frozen dataclass + StrEnum，无 Any）.

对齐 spec §6 数据约束；五态枚举与 ToolResultStatus 对齐。
全部 frozen：不可变、可哈希、可安全跨线程（并行检查器/循环）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# ── 路径 A：参数预检 ──

@dataclass(frozen=True)
class FieldError:
    """字段级错误（嵌套路径如 "steps[2].executor"）."""

    field_path: str
    expected_type: str
    actual_type: str
    message: str


@dataclass(frozen=True)
class PreCheckResult:
    """参数预检结果（spec §6.1）."""

    valid: bool
    errors: tuple[FieldError, ...] = ()

    def to_guidance_feedback(self) -> str:
        """字段级引导反馈文本（引导 LLM 自主更正后重试）."""
        if self.valid:
            return "[参数预检] 通过"
        lines = [f"[参数预检失败] 共 {len(self.errors)} 处参数错误，请更正后重试："]
        for e in self.errors:
            lines.append(
                f"  字段 '{e.field_path}' expected {e.expected_type}, got {e.actual_type}"
                f" —— {e.message}"
            )
        return "\n".join(lines)


# ── 路径 D：静态检查 ──

class CheckOverallStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class CheckerStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class CheckIssue:
    """单条检查问题（spec §6.2）."""

    file_path: str
    line: int
    column: int
    code: str
    message: str
    severity: Severity


@dataclass(frozen=True)
class CheckerResult:
    """单检查器结果（spec §6.2）."""

    checker_name: str
    status: CheckerStatus
    issues: tuple[CheckIssue, ...] = ()


@dataclass(frozen=True)
class StaticCheckResult:
    """静态检查链结果（spec §6.2）."""

    file_path: str
    language: str
    overall_status: CheckOverallStatus
    checkers: tuple[CheckerResult, ...] = ()

    def to_feedback_section(self) -> str:
        """五态回执格式的问题清单（含 [状态: xxx] 标注）."""
        lines = [f"[状态: {self.overall_status.value}] 静态检查（{self.language}）: {self.file_path}"]
        for c in self.checkers:
            lines.append(f"  [{c.checker_name}] {c.status.value}"
                         + (f"（{len(c.issues)} 问题）" if c.issues else ""))
            for iss in c.issues[:20]:  # 单检查器最多 20 条防超长
                lines.append(
                    f"    {iss.file_path}:{iss.line}:{iss.column} [{iss.severity.value}] "
                    f"{iss.code}: {iss.message}"
                )
            if len(c.issues) > 20:
                lines.append(f"    …（共 {len(c.issues)} 条，已截断）")
        return "\n".join(lines)


# ── 路径 E：上下文约定 ──

class ConventionType(StrEnum):
    IMPORT_STYLE = "import_style"
    NAMING = "naming"
    TYPE_ANNOTATION = "type_annotation"
    ERROR_HANDLING = "error_handling"


@dataclass(frozen=True)
class ConventionItem:
    """单条约定（spec §6.3）."""

    convention_type: ConventionType
    content: str


@dataclass(frozen=True)
class ConventionSummary:
    """约定提取摘要（spec §6.3）."""

    target_path: str
    conventions: tuple[ConventionItem, ...] = ()
    source_files: tuple[str, ...] = ()
    truncated: bool = False
    original_size: int = 0
    retained_size: int = 0

    def to_injection_text(self) -> str:
        """注入文本（体积受控，截断标注）."""
        if not self.conventions:
            return ""
        lines = ["[代码约定] 同目录既有代码约定（供后续编辑参考）："]
        for c in self.conventions:
            lines.append(f"  [{c.convention_type.value}] {c.content}")
        if self.truncated:
            lines.append(f"（约定已截断：原始 {self.original_size} 字符，保留 {self.retained_size} 字符）")
        if self.source_files:
            lines.append(f"（来源: {', '.join(self.source_files[:5])}）")
        return "\n".join(lines)


# ── 路径 H：错误定位 ──

class TestFramework(StrEnum):
    PYTEST = "pytest"
    RUFF = "ruff"
    PYRIGHT = "pyright"
    GENERIC = "generic"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FailureInfo:
    """单条失败信息（spec §6.4）."""

    file_path: str
    line_number: int
    reason: str
    code_snippet: str = ""
    assert_expression: str = ""


@dataclass(frozen=True)
class ErrorLocationResult:
    """错误定位结果（spec §6.4）."""

    framework: TestFramework
    failures: tuple[FailureInfo, ...] = ()
    fallback: bool = False
    original_output: str = ""
    truncated: bool = False
    original_size: int = 0
    retained_size: int = 0

    def to_injection_text(self) -> str:
        """结构化错误定位注入文本（替代原始全文，减 token 开销）."""
        if self.fallback:
            return f"[错误定位] 解析失败已回退原始输出（{len(self.original_output)} 字符）:\n{self.original_output[:self.retained_size or 4000]}"
        lines = [f"[错误定位] 框架: {self.framework.value}，失败 {len(self.failures)} 项："]
        for f in self.failures:
            lines.append(f"  {f.file_path}:{f.line_number} —— {f.reason}")
            if f.assert_expression:
                lines.append(f"    assert: {f.assert_expression}")
            if f.code_snippet:
                snippet = f.code_snippet.replace("\n", "\n    ")
                lines.append(f"    代码: {snippet}")
        if self.truncated:
            lines.append(f"（已截断：原始 {self.original_size} 字符，保留 {self.retained_size} 字符，优先保留失败位置与原因）")
        return "\n".join(lines)


# ── 路径 I：修复循环 ──

class FixLoopFinalStatus(StrEnum):
    PASSED = "passed"
    LIMIT_REACHED = "limit_reached"
    FUSE_TRIGGERED = "fuse_triggered"
    ERROR = "error"


@dataclass(frozen=True)
class RoundRecord:
    """单轮迭代记录（spec §6.5）."""

    round_number: int
    check_result: str = ""
    location_info: str = ""
    fix_action: str = ""
    rerun_result: str = ""


@dataclass(frozen=True)
class FixLoopRecord:
    """修复循环记录（spec §6.5）."""

    loop_id: str
    trace_id: str
    max_rounds: int
    rounds: tuple[RoundRecord, ...] = ()
    final_status: FixLoopFinalStatus = FixLoopFinalStatus.ERROR
    unfixed_items: tuple[str, ...] = ()
    fuse_count: int = 3

    def to_feedback_section(self) -> str:
        """终态如实汇报（含轮数/每轮摘要/最终状态/未修复项）."""
        lines = [
            f"[状态: {self.final_status.value}] 修复循环 {self.loop_id}"
            f"（trace={self.trace_id}，执行 {len(self.rounds)}/{self.max_rounds} 轮）"
        ]
        for r in self.rounds:
            lines.append(f"  第{r.round_number}轮: 检查={r.check_result or '-'}"
                         f" 定位={r.location_info or '-'} 修复={r.fix_action or '-'} 重跑={r.rerun_result or '-'}")
        if self.final_status != FixLoopFinalStatus.PASSED:
            lines.append("  未修复项: " + (", ".join(self.unfixed_items) if self.unfixed_items else "（无明细）"))
        if self.final_status == FixLoopFinalStatus.FUSE_TRIGGERED:
            lines.append(f"  熔断: 连续 {self.fuse_count} 次修复同一错误未通过")
        return "\n".join(lines)


# ── 路径 K：回归保护 ──

class DepNodeType(StrEnum):
    MODULE = "module"
    TEST = "test"


class DepRelation(StrEnum):
    IMPORTS = "imports"
    IMPORTED_BY = "imported_by"


@dataclass(frozen=True)
class DepNode:
    """依赖图节点（spec §6.6）."""

    node_type: DepNodeType
    node_id: str
    file_path: str


@dataclass(frozen=True)
class DepEdge:
    """依赖图边（spec §6.6）."""

    source_node: str
    target_node: str
    relation: DepRelation


@dataclass(frozen=True)
class RegressionResult:
    """回归保护结果（spec §6.6 + 5.6）."""

    modified_files: tuple[str, ...]
    affected_tests: tuple[str, ...] = ()
    subset_ratio: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    failures: tuple[FailureInfo, ...] = ()
    depgraph_available: bool = False
    fallback_full: bool = False

    def to_feedback_section(self) -> str:
        """测试子集执行结果回执（含子集范围/通过失败计数/失败详情）."""
        if self.fallback_full:
            lines = ["[状态: success] 回归保护（依赖图不可用，回退全量测试）"]
        elif not self.affected_tests:
            lines = ["[状态: success] 回归保护：无受影响测试，未执行"]
        else:
            lines = [
                f"[状态: {'success' if self.failed_count == 0 else 'failure'}] 回归保护: "
                f"受影响测试 {len(self.affected_tests)} 个（全量占比 {self.subset_ratio:.0%}）"
                f"，通过 {self.passed_count} / 失败 {self.failed_count}"
            ]
            for f in self.failures:
                lines.append(f"  {f.file_path}:{f.line_number} —— {f.reason}")
        lines.append("（受影响文件: " + ", ".join(self.modified_files) + "）")
        return "\n".join(lines)
