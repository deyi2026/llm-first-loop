"""路径 H：错误自动定位增强（design.md §2.1 / spec §5.4）.

execute_command 执行测试命令后，检测输出含测试失败/stack trace 时自动解析，
结构化错误信息（失败位置/原因/代码片段/assert 表达式）替代原始全文注入 LLM，
减少 trace 解析 token 开销。

多框架支持: pytest / ruff / pyright / 通用 stack trace（按输出特征自动识别）。
解析失败回退原始输出（fail-open）；不臆造失败信息（每项可在原始输出找证据）。
时延: 纯文本解析 < 2s（spec §4.1.4）；注入体积上限 max_chars（spec §4.1.7）。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Protocol

from llm_loop.task_quality.models import ErrorLocationResult, FailureInfo, TestFramework

logger = logging.getLogger(__name__)


class ErrorParser(Protocol):
    """错误解析器协议（新增格式经配置扩展）."""

    name: str

    def matches(self, output: str, command: str = "") -> bool: ...

    def parse(self, output: str) -> list[FailureInfo]: ...


class PytestParser:
    """pytest 失败输出解析: FAILED 行 + 'E   assert' + 'file.py:42' 定位."""

    name = "pytest"

    # FAILED tests/test_x.py::test_y - AssertionError: msg
    _FAILED_RE = re.compile(r"FAILED\s+([\w./\-]+\.py)::([\w\[\]/\-]+)\s+-\s+(.*)")
    # tests/test_x.py:42: in test_y
    _LOC_RE = re.compile(r"([\w./\-]+\.py):(\d+):\s+in\s+(\w+)")
    # E   assert x == 2
    _ASSERT_RE = re.compile(r"^\s*E\s+(assert\s+.+)$", re.M)

    def matches(self, output: str, command: str = "") -> bool:
        return bool(self._FAILED_RE.search(output)) or bool(self._LOC_RE.search(output))

    def parse(self, output: str) -> list[FailureInfo]:
        failures: list[FailureInfo] = []
        # 先按 FAILED 行提取失败摘要
        for m in self._FAILED_RE.finditer(output):
            fpath, _test, reason = m.group(1), m.group(2), m.group(3).strip()
            line = self._find_line(output, fpath)
            failures.append(FailureInfo(
                file_path=fpath, line_number=line, reason=reason[:300],
                code_snippet=self._snippet(fpath, line), assert_expression="",
            ))
        # 无 FAILED 行但有定位行（断言失败在文件内）
        if not failures:
            for m in self._LOC_RE.finditer(output):
                fpath, lineno = m.group(1), int(m.group(2))
                reason = self._nearby_assert(output)
                failures.append(FailureInfo(
                    file_path=fpath, line_number=lineno, reason=reason,
                    code_snippet=self._snippet(fpath, lineno),
                    assert_expression=reason if reason.startswith("assert") else "",
                ))
        return failures

    @staticmethod
    def _find_line(output: str, fpath: str) -> int:
        m = re.search(rf"{re.escape(fpath)}:(\d+)", output)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _nearby_assert(output: str) -> str:
        for m in PytestParser._ASSERT_RE.finditer(output):
            return m.group(1)[:200]
        return "assert failed"

    @staticmethod
    def _snippet(fpath: str, line: int) -> str:
        if line <= 0:
            return ""
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if 1 <= line <= len(lines):
                return lines[line - 1].strip()[:200]
        except OSError:
            pass
        return ""


class RuffParser:
    """ruff 输出解析: x.py:42:5: CODE Message."""

    name = "ruff"
    _RE = re.compile(r"([\w./\-]+\.py):(\d+):(\d+):\s+([A-Z]\d+)\s+(.*)")

    def matches(self, output: str, command: str = "") -> bool:
        return bool(self._RE.search(output))

    def parse(self, output: str) -> list[FailureInfo]:
        out: list[FailureInfo] = []
        for m in self._RE.finditer(output):
            out.append(FailureInfo(
                file_path=m.group(1), line_number=int(m.group(2)),
                reason=f"{m.group(4)}: {m.group(5).strip()[:200]}",
                code_snippet=PytestParser._snippet(m.group(1), int(m.group(2))),
                assert_expression="",
            ))
        return out


class PyrightParser:
    """pyright 输出解析: x.py:42:5 - error: Message."""

    name = "pyright"
    _RE = re.compile(r"([\w./\-]+\.py):(\d+):(\d+)\s+-\s+(error|warning|information):\s+(.*)")

    def matches(self, output: str, command: str = "") -> bool:
        return bool(self._RE.search(output))

    def parse(self, output: str) -> list[FailureInfo]:
        out: list[FailureInfo] = []
        for m in self._RE.finditer(output):
            out.append(FailureInfo(
                file_path=m.group(1), line_number=int(m.group(2)),
                reason=f"{m.group(4)}: {m.group(5).strip()[:200]}",
                code_snippet=PytestParser._snippet(m.group(1), int(m.group(2))),
                assert_expression="",
            ))
        return out


class GenericTraceParser:
    """通用 stack trace: 'File \"x.py\", line 42' + 'Error: Message'."""

    name = "generic"
    _FILE_RE = re.compile(r'File\s+"([^"]+\.py)",\s+line\s+(\d+)')
    _ERR_RE = re.compile(r"^(\w+(?:Error|Exception|Failure)):\s*(.*)$", re.M)

    def matches(self, output: str, command: str = "") -> bool:
        return bool(self._FILE_RE.search(output)) and bool(self._ERR_RE.search(output))

    def parse(self, output: str) -> list[FailureInfo]:
        files = self._FILE_RE.findall(output)
        err = self._ERR_RE.search(output)
        reason = f"{err.group(1)}: {err.group(2)[:200]}" if err else "error"
        out: list[FailureInfo] = []
        for fpath, lineno in files[:10]:  # 最多 10 帧
            out.append(FailureInfo(
                file_path=fpath, line_number=int(lineno), reason=reason,
                code_snippet=PytestParser._snippet(fpath, int(lineno)),
                assert_expression="",
            ))
        return out or [FailureInfo(file_path="", line_number=0, reason=reason)]


class ErrorLocator:
    """错误定位器（多格式识别 + 结构化输出 + fail-open 回退）."""

    def __init__(
        self,
        *,
        max_chars: int = 2000,
        parsers: tuple[ErrorParser, ...] | None = None,
        event_store: Any | None = None,
        session_id: str = "",
    ) -> None:
        self._max_chars = max_chars
        self._parsers: tuple[ErrorParser, ...] = parsers or (
            PytestParser(), RuffParser(), PyrightParser(), GenericTraceParser(),
        )
        self._event_store = event_store
        self._session_id = session_id

    def locate(self, output: str, command: str = "") -> ErrorLocationResult:
        """解析命令输出为结构化错误信息（解析失败回退原始输出）.

        Args:
            output: 命令输出全文。
            command: 触发命令（解析器可据此辅助识别，如 pytest 前缀）。

        Returns:
            ErrorLocationResult（framework/failures 或 fallback=True + original_output）。
        """
        start = time.perf_counter()
        original_size = len(output)
        # 无输出/无失败特征 → 不触发解析（非测试输出）
        if not output or len(output.strip()) < 10:
            return ErrorLocationResult(
                framework=TestFramework.UNKNOWN, fallback=True,
                original_output=output, original_size=original_size,
                retained_size=original_size,
            )

        matched: ErrorParser | None = None
        try:
            for p in self._parsers:
                if p.matches(output, command):
                    matched = p
                    break
        except Exception:  # noqa: BLE001 — 匹配异常回退
            logger.warning("错误定位匹配异常（回退原始输出）: %s", exc_info=True)
            return ErrorLocationResult(
                framework=TestFramework.UNKNOWN, fallback=True,
                original_output=output, original_size=original_size,
                retained_size=original_size,
            )

        if matched is None:
            # 格式不识别 → 回退原始输出（fail-open，不编造）
            return ErrorLocationResult(
                framework=TestFramework.UNKNOWN, fallback=True,
                original_output=output, original_size=original_size,
                retained_size=original_size,
            )

        try:
            failures = tuple(matched.parse(output))
        except Exception as exc:  # noqa: BLE001 — 解析异常回退
            logger.warning("错误定位解析异常（回退原始输出）: %s", exc)
            return ErrorLocationResult(
                framework=TestFramework.UNKNOWN, fallback=True,
                original_output=output, original_size=original_size,
                retained_size=original_size,
            )

        # 框架名映射到枚举
        fw_map = {
            "pytest": TestFramework.PYTEST, "ruff": TestFramework.RUFF,
            "pyright": TestFramework.PYRIGHT, "generic": TestFramework.GENERIC,
        }
        framework = fw_map.get(matched.name, TestFramework.UNKNOWN)

        # 体积控制: 结构化文本超限截断（优先保留位置与原因）
        result = ErrorLocationResult(
            framework=framework, failures=failures,
            original_size=original_size, retained_size=original_size,
        )
        structured = result.to_injection_text()
        if len(structured) > self._max_chars:
            # 截断: 保留前 max_chars*0.6 字符（失败位置与原因在前部）
            kept = structured[: self._max_chars]
            result = ErrorLocationResult(
                framework=framework, failures=failures,
                truncated=True, original_size=original_size,
                retained_size=len(kept),
            )
            # failures 超限时也裁剪
            if len(result.to_injection_text()) > self._max_chars:
                trimmed = tuple(failures[:3])
                result = ErrorLocationResult(
                    framework=framework, failures=trimmed,
                    truncated=True, original_size=original_size,
                    retained_size=len(kept),
                )

        # 事件落盘（不含原始全文，仅统计）
        if self._event_store is not None:
            try:
                self._event_store.append(
                    self._session_id, "task.error_locate.parsed",
                    {
                        "framework": framework.value,
                        "failure_count": len(failures),
                        "fallback": False,
                        "original_size": original_size,
                        "structured_size": len(structured),
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    },
                )
            except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open
                logger.warning("错误定位事件落盘失败（fail-open）", exc_info=True)
        return result


# 协议别名（tasks.md §1.4）
ErrorLocatorProtocol = ErrorLocator
