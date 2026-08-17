"""路径 D：生成后自动静态检查链（design.md §2.1 / spec §5.2）.

代码写入文件后（edit_file 成功后）自动触发语言对应静态检查器，
检查结果以五态回执 LLM，LLM 可即时修正。

- 语言对应: python → ruff + pyright（其他语言经配置扩展）
- 并行执行: concurrent.futures.ThreadPoolExecutor
- 独立超时: timeout_s（缺省 30s），超时该检查器 TIMEOUT 其余继续
- 检查器不可用/执行失败 → SKIPPED/ERROR 其余继续（fail-open）
- severity_filter 过滤（空=不过滤）
- overall_status 聚合（error=FAILURE/全过=SUCCESS/失败=ERROR/超时=TIMEOUT/无检查器=SKIPPED）
- 禁止自动修改代码（只报告问题，修正归 LLM）
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from llm_loop.task_quality.models import (
    CheckerResult,
    CheckerStatus,
    CheckIssue,
    CheckOverallStatus,
    Severity,
    StaticCheckResult,
)

logger = logging.getLogger(__name__)

# 语言 → 检查器映射（缺省 python；其他语言经配置扩展）
_LANG_CHECKERS: dict[str, tuple[str, ...]] = {
    "python": ("ruff", "pyright"),
}

# 检查器命令模板（{file_path} 占位；--output-format 保证输出可解析）
_CMD_TEMPLATES: dict[str, list[str]] = {
    "ruff": ["{bin}", "check", "--output-format", "concise", "{file_path}"],
    "pyright": ["{bin}", "{file_path}"],
}

# ruff 输出: x.py:42:5: E501 Message（错误码）或 x.py:42:5: invalid-syntax: Message（无码）
# 两条路径分别匹配（错误码优先，无码用 RUFF 占位）
_RUFF_RE = re.compile(r"([\w./\-]+\.py):(\d+):(\d+):\s+([A-Z]\d+)\s+(.*)")
_RUFF_NOSYNTAX_RE = re.compile(r"([\w./\-]+\.py):(\d+):(\d+):\s+([a-z\-]+):\s*(.*)")
# pyright 输出: x.py:42:5 - error: Message
_PYRIGHT_RE = re.compile(r"([\w./\-]+\.py):(\d+):(\d+)\s+-\s+(error|warning|information):\s+(.*)")

_SEVERITY_MAP = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}


class StaticCheckChain:
    """静态检查链（语言对应检查器并行执行 + 超时 + fail-open）."""

    def __init__(
        self,
        *,
        checkers: tuple[str, ...] | None = None,
        severity_filter: frozenset[str] = frozenset(),
        timeout_s: float = 30.0,
        command_runner: Callable[[str], tuple[int, str]] | None = None,
        event_store: Any | None = None,
        session_id: str = "",
        env_bin_dir: str = "",
    ) -> None:
        self._checkers = checkers
        self._severity_filter = severity_filter
        self._timeout_s = timeout_s
        self._command_runner = command_runner
        self._event_store = event_store
        self._session_id = session_id
        self._env_bin = env_bin_dir or ""

    def run(self, file_path: str, language: str = "python") -> StaticCheckResult:
        """按语言运行静态检查链（并行检查器）.

        Args:
            file_path: 被检查文件路径。
            language: 文件语言（缺省 python）。

        Returns:
            StaticCheckResult（overall_status + checkers 明细）。
        """
        start = time.perf_counter()
        # 语言无对应检查器 → SKIPPED（不标注异常，正常跳过）
        enabled = self._checkers or _LANG_CHECKERS.get(language, ())
        if not enabled:
            return StaticCheckResult(
                file_path=file_path, language=language,
                overall_status=CheckOverallStatus.SKIPPED,
                checkers=(),
            )

        # 并行执行各检查器
        results: list[CheckerResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(enabled)) as pool:
            futures = {pool.submit(self._run_checker, name, file_path): name for name in enabled}
            for fut in concurrent.futures.as_completed(futures):
                name = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001 — 单检查器异常不阻断整体
                    logger.warning("检查器 %s 异常（标记 ERROR）: %s", name, exc)
                    results.append(CheckerResult(name, CheckerStatus.ERROR))

        # 聚合 overall_status（按优先级: ERROR > FAILURE > TIMEOUT > SUCCESS > SKIPPED）
        overall = self._aggregate(results)

        result = StaticCheckResult(
            file_path=file_path, language=language,
            overall_status=overall, checkers=tuple(results),
        )

        # 事件落盘（统计，不含源码）
        if self._event_store is not None:
            try:
                self._event_store.append(
                    self._session_id, "task.static_check.completed",
                    {
                        "file_path": file_path, "language": language,
                        "overall_status": overall.value,
                        "checker_count": len(results),
                        "issue_count": sum(len(c.issues) for c in results),
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    },
                )
            except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open
                logger.warning("静态检查事件落盘失败（fail-open）", exc_info=True)
        return result

    def _run_checker(self, name: str, file_path: str) -> CheckerResult:
        """执行单个检查器（超时/不可用 fail-open）."""
        # 注入 command_runner 且未显式指定 env_bin_dir 时跳过本机探测（runner 接管执行，
        # 测试/隔离场景）；显式 env_bin_dir（含指向空目录模拟缺失）仍走探测 → SKIPPED
        if self._command_runner is not None and not self._env_bin:
            bin_path = name
        else:
            bin_path = self._find_bin(name)
            if bin_path is None:
                return CheckerResult(name, CheckerStatus.SKIPPED)

        cmd = [part.replace("{bin}", bin_path).replace("{file_path}", file_path)
               for part in _CMD_TEMPLATES[name]]

        # 注入 command_runner 优先（测试/隔离场景）；缺省 subprocess 执行
        if self._command_runner is not None:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(self._command_runner, " ".join(cmd))
                    exit_code, output = fut.result(timeout=self._timeout_s)
            except concurrent.futures.TimeoutError:
                return CheckerResult(name, CheckerStatus.TIMEOUT)
            except Exception as exc:  # noqa: BLE001 — 执行失败
                logger.warning("检查器 %s 执行失败: %s", name, exc)
                return CheckerResult(name, CheckerStatus.ERROR)
        else:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self._timeout_s,
                )
                output = (proc.stdout or "") + (proc.stderr or "")
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                return CheckerResult(name, CheckerStatus.TIMEOUT)
            except Exception as exc:  # noqa: BLE001 — 执行失败
                logger.warning("检查器 %s 执行失败: %s", name, exc)
                return CheckerResult(name, CheckerStatus.ERROR)

        issues = self._parse_output(name, output)
        # severity_filter 过滤
        if self._severity_filter:
            issues = tuple(i for i in issues if i.severity.value not in self._severity_filter)

        # 状态: 有 error 级问题=FAILURE；exit_code!=0 且无 error（如内部错误）=ERROR；否则 SUCCESS
        if any(i.severity == Severity.ERROR for i in issues):
            status = CheckerStatus.FAILURE
        elif exit_code != 0 and not issues:
            status = CheckerStatus.ERROR
        else:
            status = CheckerStatus.SUCCESS
        return CheckerResult(name, status, issues)

    def _find_bin(self, name: str) -> str | None:
        """定位检查器可执行文件（env_bin_dir 指定时只用该目录，否则 PATH）."""
        if self._env_bin:
            candidate = f"{self._env_bin}/{name}"
            return candidate if shutil.which(candidate) else None
        return name if shutil.which(name) else None

    def _parse_output(self, checker: str, output: str) -> tuple[CheckIssue, ...]:
        """解析检查器输出为 CheckIssue 清单."""
        issues: list[CheckIssue] = []
        if checker == "ruff":
            # 错误码格式优先；无码（invalid-syntax）用第二个正则 + RUFF 占位
            for m in _RUFF_RE.finditer(output):
                issues.append(CheckIssue(
                    file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
                    code=m.group(4), message=m.group(5).strip()[:200],
                    severity=Severity.ERROR,
                ))
            if not issues:
                for m in _RUFF_NOSYNTAX_RE.finditer(output):
                    issues.append(CheckIssue(
                        file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
                        code="RUFF", message=(m.group(4) + ": " + m.group(5)).strip()[:200],
                        severity=Severity.ERROR,
                    ))
        elif checker == "pyright":
            for m in _PYRIGHT_RE.finditer(output):
                sev = _SEVERITY_MAP.get(m.group(3), Severity.WARNING)
                issues.append(CheckIssue(
                    file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
                    code="pyright", message=m.group(5).strip()[:200],
                    severity=sev,
                ))
        return tuple(issues)

    @staticmethod
    def _aggregate(results: list[CheckerResult]) -> CheckOverallStatus:
        """聚合整体状态（ERROR > FAILURE > TIMEOUT > SUCCESS > SKIPPED）."""
        if not results:
            return CheckOverallStatus.SKIPPED
        statuses = [r.status for r in results]
        if CheckerStatus.ERROR in statuses:
            return CheckOverallStatus.ERROR
        if CheckerStatus.FAILURE in statuses:
            return CheckOverallStatus.FAILURE
        if CheckerStatus.TIMEOUT in statuses:
            return CheckOverallStatus.TIMEOUT
        if all(s == CheckerStatus.SUCCESS for s in statuses):
            return CheckOverallStatus.SUCCESS
        return CheckOverallStatus.SKIPPED  # 全部 skipped 或无有效结果


# 协议别名（tasks.md §1.3）
StaticCheckChainProtocol = StaticCheckChain
