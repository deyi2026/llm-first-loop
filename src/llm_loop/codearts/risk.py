"""RiskClassifier 风险分类器（design.md §2.2.2.7）.

判定委派任务风险等级（normal/catastrophic）。灾难性动作模式匹配
（生产部署/制品发布/仓库强推/环境销毁）。本地灾难性安全硬边界前置检查
（复用 CatastrophicGuard，禁止经 CodeArts 绕过本地安全边界）。

凭证明文不进 RiskAssessment（纯判定结果）。
"""

from __future__ import annotations

import re
from typing import Protocol

from llm_loop.codearts.models import DispatchTask, RiskAssessment, RiskLevel
from llm_loop.tools.safety import CatastrophicGuard

# 灾难性动作模式（spec §2 领域术语"灾难性动作"）
# 生产部署 / 制品发布 / 仓库强推 / 环境销毁
_CATASTROPHIC_TASK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("生产环境部署", re.compile(r"production\s+deploy|deploy\s+to\s+prod|生产部署|部署到生产", re.IGNORECASE)),
    ("制品发布", re.compile(r"publish\s+artifact|release\s+artifact|制品发布|发布制品", re.IGNORECASE)),
    ("仓库强制推送", re.compile(r"force\s+push|git\s+push\s+(-f|--force)|仓库强推|强制推送", re.IGNORECASE)),
    ("环境销毁", re.compile(r"destroy\s+environment|terraform\s+destroy|环境销毁|销毁环境", re.IGNORECASE)),
    ("数据库破坏性操作", re.compile(r"\bdrop\s+(database|table|schema)|truncate\s+table|数据库销毁", re.IGNORECASE)),
]


class RiskClassifier(Protocol):
    """风险分类器协议（design.md §2.2.2.7 扩展点 2）."""

    def classify(self, task: DispatchTask) -> RiskAssessment: ...


class PatternRiskClassifier:
    """模式匹配风险分类器（默认实现）.

    1. 本地灾难性安全硬边界前置检查：经 CatastrophicGuard.guard 以 execute_command
       语义扫描任务描述文本，命中则 local_blocked=True（禁止经 CodeArts 绕过）。
    2. 灾难性动作模式匹配：扫描 task_description 与 context_summary 中的关键词模式。
    """

    def __init__(self, safety_guard: CatastrophicGuard) -> None:
        self._guard = safety_guard

    def classify(self, task: DispatchTask) -> RiskAssessment:
        # 1. 本地灾难性安全硬边界前置检查（以 execute_command 语义扫描任务描述）
        block = self._guard.guard("execute_command", {"command": task.task_description})
        if block is not None and block.blocked:
            return RiskAssessment(
                level=RiskLevel.CATASTROPHIC,
                reason=f"命中本地灾难性安全硬边界: {block.reason}",
                evidence=block.evidence,
                local_blocked=True,
                local_block_reason=block.reason,
            )

        # 2. 灾难性动作模式匹配（扫描任务描述 + 上下文摘要）
        scan_text = f"{task.task_description}\n{task.context_summary}"
        for label, pattern in _CATASTROPHIC_TASK_PATTERNS:
            m = pattern.search(scan_text)
            if m:
                return RiskAssessment(
                    level=RiskLevel.CATASTROPHIC,
                    reason=f"灾难性动作: {label}",
                    evidence=f"命中模式: {m.group(0)}",
                    local_blocked=False,
                )

        # 3. 常规任务
        return RiskAssessment(
            level=RiskLevel.NORMAL,
            reason="未命中灾难性动作模式",
            evidence="",
            local_blocked=False,
        )
