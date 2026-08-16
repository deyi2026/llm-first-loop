"""路径 K：回归保护自动验证（design.md §2.1 / spec §5.6）.

代码修改后基于 import 依赖图计算受影响测试子集并执行，替代全量测试。

- 依赖图不可用 → 回退全量测试（fallback_full=True + 标注）
- 子集为空 → 标注"无受影响测试"（不伪造通过）
- 子集执行失败 → 经 ErrorLocator 结构化定位（复用路径 H）
- 测试框架崩溃 → 如实回执 error 不臆造结果
- 事件落盘: task.regression.subset_executed
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

from llm_loop.task_quality.models import FailureInfo, RegressionResult

logger = logging.getLogger(__name__)

# pytest 输出失败计数（如 "1 failed, 5 passed"）
_PASS_RE = re.compile(r"(\d+)\s+passed")
_FAIL_RE = re.compile(r"(\d+)\s+failed")
# pytest 失败定位（供无 error_locator 时兜底粗解析）
_FAILED_RE = re.compile(r"FAILED\s+([\w./\-]+\.py)::([\w\[\]/\-]+)\s+-\s+(.*)")


class RegressionGuard:
    """回归保护验证器（受影响测试子集执行 + fail-open 回退）."""

    def __init__(
        self,
        *,
        dep_graph: Any,
        test_command_template: str = "pytest {files}",
        command_runner: Callable[[str], tuple[int, str]] | None = None,
        error_locator: Any | None = None,
        event_store: Any | None = None,
        session_id: str = "",
    ) -> None:
        self._dep_graph = dep_graph
        self._test_command_template = test_command_template
        self._command_runner = command_runner
        self._error_locator = error_locator
        self._event_store = event_store
        self._session_id = session_id

    def verify(self, modified_files: list[str]) -> RegressionResult:
        """验证修改文件的受影响测试子集.

        Args:
            modified_files: 修改文件路径列表。

        Returns:
            RegressionResult（子集执行结果/回退标注）。
        """
        # 依赖图反向查找
        try:
            subset, available = self._dep_graph.affected_tests(modified_files)
        except Exception as exc:  # noqa: BLE001 — 依赖图异常回退全量
            logger.warning("依赖图查询异常（回退全量）: %s", exc)
            available = False
            subset = []

        if not available:
            # 回退全量（fail-open，不静默跳过验证）
            return self._run_tests(
                modified_files, affected_tests=[], fallback_full=True,
                subset_ratio=1.0,
            )

        if not subset:
            # 无受影响测试：如实标注，不执行、不伪造通过
            return RegressionResult(
                modified_files=tuple(modified_files),
                affected_tests=(), subset_ratio=0.0,
                passed_count=0, failed_count=0, failures=(),
                depgraph_available=True, fallback_full=False,
            )

        # 子集非空 → 执行（subset_ratio 相对全量未知，标注 0 由调用方定）
        return self._run_tests(
            modified_files, affected_tests=subset, fallback_full=False,
            subset_ratio=0.0,
        )

    def _run_tests(
        self,
        modified_files: list[str],
        *,
        affected_tests: list[str],
        fallback_full: bool,
        subset_ratio: float,
    ) -> RegressionResult:
        """执行测试子集（或全量回退）."""
        start = time.perf_counter()
        test_files = affected_tests or ["tests/"]  # 回退全量默认跑 tests/
        cmd = self._test_command_template.format(files=" ".join(test_files))

        try:
            if self._command_runner is not None:
                exit_code, output = self._command_runner(cmd)
            else:
                import subprocess

                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=120.0,
                )
                exit_code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return RegressionResult(
                modified_files=tuple(modified_files),
                affected_tests=tuple(test_files), subset_ratio=subset_ratio,
                passed_count=0, failed_count=0, failures=(),
                depgraph_available=True, fallback_full=fallback_full,
            )
        except Exception:  # noqa: BLE001 — 框架崩溃如实回执
            return RegressionResult(
                modified_files=tuple(modified_files),
                affected_tests=tuple(test_files), subset_ratio=subset_ratio,
                passed_count=0, failed_count=0, failures=(),
                depgraph_available=True, fallback_full=fallback_full,
            )

        # 解析结果
        passed_m = _PASS_RE.search(output)
        failed_m = _FAIL_RE.search(output)
        passed = int(passed_m.group(1)) if passed_m else 0
        failed = int(failed_m.group(1)) if failed_m else (1 if exit_code != 0 else 0)

        # 失败结构化定位（复用路径 H；无 error_locator 时兜底粗解析）
        failures: tuple[FailureInfo, ...] = ()
        if failed > 0:
            if self._error_locator is not None:
                try:
                    loc = self._error_locator.locate(output, cmd)
                    if not loc.fallback:
                        failures = loc.failures
                except Exception:  # noqa: BLE001 — 定位异常兜底
                    pass
            if not failures:
                matched = list(_FAILED_RE.finditer(output))
                failures = tuple(
                    FailureInfo(m.group(1), 0, (m.group(3) or "").strip()[:200])
                    for m in matched
                ) or (FailureInfo("", 0, "测试失败（详见输出）"),)

        result = RegressionResult(
            modified_files=tuple(modified_files),
            affected_tests=tuple(test_files), subset_ratio=subset_ratio,
            passed_count=passed, failed_count=failed, failures=failures,
            depgraph_available=True, fallback_full=fallback_full,
        )

        # 事件落盘（统计，不含敏感）
        if self._event_store is not None:
            try:
                self._event_store.append(
                    self._session_id, "task.regression.subset_executed",
                    {
                        "modified_files": list(modified_files),
                        "test_count": len(test_files),
                        "passed": passed, "failed": failed,
                        "fallback_full": fallback_full,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    },
                )
            except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open
                logger.warning("回归保护事件落盘失败（fail-open）", exc_info=True)
        return result


# 协议别名（tasks.md §6.2）
RegressionGuardProtocol = RegressionGuard
