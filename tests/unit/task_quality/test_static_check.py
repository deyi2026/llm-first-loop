"""路径 D 静态检查链测试（tasks.md §1.3 验收）."""

from __future__ import annotations

import time

from llm_loop.task_quality.models import CheckerStatus, CheckOverallStatus, Severity
from llm_loop.task_quality.static_check import StaticCheckChain


class _FakeRunner:
    """command_runner 桩: 按命令返回预设输出（免真实检查器）."""

    def __init__(self, outputs: dict[str, tuple[int, str]], delay: float = 0.0):
        self._outputs = outputs
        self._delay = delay
        self.calls: list[str] = []

    def __call__(self, cmd: str) -> tuple[int, str]:
        self.calls.append(cmd)
        if self._delay:
            time.sleep(self._delay)
        for key, (code, out) in self._outputs.items():
            if key in cmd:
                return code, out
        return 0, ""


RUFF_OK = ""
RUFF_ERR = "tests/test_x.py:10:5: E501 Line too long (99 > 88)\ntests/test_x.py:12:1: F401 'os' imported but unused\nFound 2 errors."
PYRIGHT_OK = ""
PYRIGHT_ERR = "tests/test_x.py:10:5 - error: Argument of type \"int\" cannot be assigned (reportArgumentType)\ntests/test_x.py:15:3 - warning: \"x\" is not defined (reportUndefinedVariable)"


def _chain(outputs: dict[str, tuple[int, str]], **kw):
    return StaticCheckChain(command_runner=_FakeRunner(outputs), **kw)


def test_language_no_checker_skipped():
    """无对应检查器语言: SKIPPED."""
    r = StaticCheckChain().run("readme.md", language="markdown")
    assert r.overall_status == CheckOverallStatus.SKIPPED
    assert r.checkers == ()


def test_all_pass_success():
    """检查全通过: SUCCESS."""
    c = _chain({"ruff": (0, RUFF_OK), "pyright": (0, PYRIGHT_OK)})
    r = c.run("tests/test_x.py")
    assert r.overall_status == CheckOverallStatus.SUCCESS
    assert len(r.checkers) == 2
    assert all(x.status == CheckerStatus.SUCCESS for x in r.checkers)


def test_error_found_failure():
    """检查发现 error: FAILURE + 问题清单（file:line:col/code/severity）."""
    c = _chain({"ruff": (1, RUFF_ERR), "pyright": (0, PYRIGHT_OK)})
    r = c.run("tests/test_x.py")
    assert r.overall_status == CheckOverallStatus.FAILURE
    ruff = next(x for x in r.checkers if x.checker_name == "ruff")
    assert ruff.status == CheckerStatus.FAILURE
    assert len(ruff.issues) == 2
    iss = ruff.issues[0]
    assert iss.file_path == "tests/test_x.py"
    assert iss.line == 10 and iss.column == 5
    assert iss.code == "E501"
    assert iss.severity == Severity.ERROR


def test_checker_missing_skipped():
    """检查器未安装: SKIPPED + 其余继续."""
    # _find_bin 找不到 ruff（无 PATH）→ 但 pyright 也会找不到；用 env_bin 指向空目录模拟
    c = StaticCheckChain(command_runner=_FakeRunner({}), env_bin_dir="/nonexistent_bin")
    r = c.run("tests/test_x.py")
    # 两个检查器都 SKIPPED → overall SKIPPED
    assert r.overall_status == CheckOverallStatus.SKIPPED
    assert all(x.status == CheckerStatus.SKIPPED for x in r.checkers)


def test_checker_timeout():
    """检查器超时: TIMEOUT 其余继续."""
    c = StaticCheckChain(
        command_runner=_FakeRunner({"ruff": (0, RUFF_OK)}, delay=5.0),
        timeout_s=0.2,
    )
    r = c.run("tests/test_x.py")
    assert r.overall_status == CheckOverallStatus.TIMEOUT
    assert any(x.status == CheckerStatus.TIMEOUT for x in r.checkers)


def test_severity_filter():
    """severity_filter: 过滤指定级别."""
    c = _chain({"ruff": (1, RUFF_ERR), "pyright": (1, PYRIGHT_ERR)},
               severity_filter=frozenset({"error"}))
    r = c.run("tests/test_x.py")
    pyright = next(x for x in r.checkers if x.checker_name == "pyright")
    # error 被过滤 → 只剩 warning（若 warning 也在 filter 则空）
    assert all(i.severity != Severity.ERROR for i in pyright.issues)


def test_parallel_execution():
    """并行执行: 两个检查器都执行（calls 含两个命令）."""
    runner = _FakeRunner({"ruff": (0, RUFF_OK), "pyright": (0, PYRIGHT_OK)})
    c = StaticCheckChain(command_runner=runner)
    c.run("tests/test_x.py")
    assert len(runner.calls) == 2


def test_event_store_completed():
    """检查完成事件落盘."""
    events = []
    class _Store:
        def append(self, sid, etype, payload):
            events.append((etype, payload))
            return None
    c = _chain({"ruff": (1, RUFF_ERR), "pyright": (0, PYRIGHT_OK)}, event_store=_Store(), session_id="s1")
    c.run("tests/test_x.py")
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "task.static_check.completed"
    assert payload["overall_status"] == "failure"
    assert payload["issue_count"] == 2


def test_feedback_section():
    """to_feedback_section: 含 [状态: xxx] 标注与问题清单."""
    c = _chain({"ruff": (1, RUFF_ERR), "pyright": (0, PYRIGHT_OK)})
    r = c.run("tests/test_x.py")
    text = r.to_feedback_section()
    assert "[状态: failure]" in text
    assert "E501" in text
    assert "tests/test_x.py:10:5" in text


def test_ruff_invalid_syntax_no_code():
    """ruff 语法错误（无错误码 invalid-syntax）: 解析为 RUFF 占位码 + error."""
    out = "tests/test_x.py:4:15: invalid-syntax: Expected an expression\nFound 1 error."
    c = _chain({"ruff": (1, out), "pyright": (0, PYRIGHT_OK)})
    r = c.run("tests/test_x.py")
    assert r.overall_status == CheckOverallStatus.FAILURE
    ruff = next(x for x in r.checkers if x.checker_name == "ruff")
    assert ruff.status == CheckerStatus.FAILURE
    assert len(ruff.issues) == 1
    assert ruff.issues[0].code == "RUFF"
    assert "Expected an expression" in ruff.issues[0].message
