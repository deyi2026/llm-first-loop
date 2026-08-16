"""任务执行成功率提升——六路径落地（task_quality 包）.

路径 A: 参数预检 + 引导反馈
路径 D: 生成后自动静态检查链
路径 E: 上下文约定注入
路径 H: 错误自动定位增强
路径 I: 修复循环编排
路径 K: 回归保护自动验证

设计对齐: .codeartsdoer/specs/task_success_rate/{spec,design,DECISIONS}.md
核心原则: 程序最小化（RULE-AI-00）+ 诚实回执五态 + fail-open 零回归。
"""

from llm_loop.task_quality.models import (
    CheckerResult,
    CheckerStatus,
    CheckIssue,
    CheckOverallStatus,
    ConventionItem,
    ConventionSummary,
    ConventionType,
    DepEdge,
    DepNode,
    DepNodeType,
    DepRelation,
    ErrorLocationResult,
    FailureInfo,
    FieldError,
    FixLoopFinalStatus,
    FixLoopRecord,
    PreCheckResult,
    RegressionResult,
    RoundRecord,
    Severity,
    StaticCheckResult,
    TestFramework,
)

__all__ = [
    "CheckIssue",
    "CheckOverallStatus",
    "CheckerResult",
    "CheckerStatus",
    "ConventionItem",
    "ConventionSummary",
    "ConventionType",
    "DepEdge",
    "DepNode",
    "DepNodeType",
    "DepRelation",
    "ErrorLocationResult",
    "FailureInfo",
    "FieldError",
    "FixLoopFinalStatus",
    "FixLoopRecord",
    "PreCheckResult",
    "RegressionResult",
    "RoundRecord",
    "Severity",
    "StaticCheckResult",
    "TestFramework",
]
