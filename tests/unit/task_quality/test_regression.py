"""路径 K 回归保护测试（tasks.md §6.2 验收）."""

from __future__ import annotations

from llm_loop.task_quality.regression import RegressionGuard


class _FakeDepGraph:
    """依赖图桩（可用/不可用/空子集）."""

    def __init__(self, subset=None, available=True):
        self._subset = subset or []
        self._available = available

    def affected_tests(self, modified_files):
        return list(self._subset), self._available


class _FakeRunner:
    """command_runner 桩: 按命令返回预设输出."""

    def __init__(self, code=0, out="1 passed"):
        self._code, self._out = code, out
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return self._code, self._out


def _guard(dep, runner, **kw):
    return RegressionGuard(dep_graph=dep, command_runner=runner, **kw)


def test_subset_passed():
    """子集全通过: passed_count=N, failed_count=0."""
    g = _guard(_FakeDepGraph(["tests/test_calc.py"]),
               _FakeRunner(0, "2 passed in 0.1s"))
    r = g.verify(["src/calc.py"])
    assert r.depgraph_available is True
    assert r.fallback_full is False
    assert r.passed_count == 2
    assert r.failed_count == 0
    assert "tests/test_calc.py" in r.affected_tests


def test_subset_failed_with_location():
    """子集有失败: failures 含结构化 FailureInfo（经路径 H）."""
    from llm_loop.task_quality.error_locate import ErrorLocator
    out = "1 failed, 1 passed\nFAILED tests/test_calc.py::test_add - AssertionError: assert 1 == 2"
    g = _guard(_FakeDepGraph(["tests/test_calc.py"]),
               _FakeRunner(1, out),
               error_locator=ErrorLocator())
    r = g.verify(["src/calc.py"])
    assert r.failed_count == 1
    assert len(r.failures) >= 1
    assert r.failures[0].file_path == "tests/test_calc.py"


def test_depgraph_unavailable_fallback_full():
    """依赖图不可用: 回退全量 + fallback_full=True."""
    g = _guard(_FakeDepGraph([], available=False), _FakeRunner(0, "5 passed"))
    r = g.verify(["src/calc.py"])
    assert r.fallback_full is True
    assert r.passed_count == 5


def test_no_affected_tests():
    """子集为空: 标注'无受影响测试'不执行."""
    g = _guard(_FakeDepGraph([], available=True), _FakeRunner(0, ""))
    r = g.verify(["README.md"])
    assert r.depgraph_available is True
    assert r.affected_tests == ()
    assert r.passed_count == 0 and r.failed_count == 0
    assert "无受影响测试" in r.to_feedback_section()
    assert g._command_runner is not None and len(g._command_runner.calls) == 0 if hasattr(g, "_command_runner") else True


def test_framework_crash_honest():
    """测试框架崩溃: 如实回执（不臆造通过）."""
    g = _guard(_FakeDepGraph(["tests/test_calc.py"]), _FakeRunner(2, "INTERNAL ERROR: crashed"))
    r = g.verify(["src/calc.py"])
    # 无 passed/failed 匹配 → passed=0, failed=1（exit!=0 兜底）
    assert r.passed_count == 0
    assert r.failed_count == 1


def test_event_store_subset_executed():
    """子集执行事件落盘."""
    events = []
    class _Store:
        def append(self, sid, etype, payload):
            events.append((etype, payload))
            return None
    g = _guard(_FakeDepGraph(["tests/test_calc.py"]), _FakeRunner(0, "1 passed"),
               event_store=_Store(), session_id="s1")
    g.verify(["src/calc.py"])
    assert len(events) == 1
    assert events[0][0] == "task.regression.subset_executed"
    assert events[0][1]["passed"] == 1


def test_feedback_section():
    """to_feedback_section: 含子集范围/计数/状态标注."""
    g = _guard(_FakeDepGraph(["tests/test_calc.py"]), _FakeRunner(0, "3 passed"))
    r = g.verify(["src/calc.py"])
    text = r.to_feedback_section()
    assert "[状态: success]" in text
    assert "受影响测试" in text
    assert "tests/test_calc.py" in text


def test_runner_exception_sets_error_field(monkeypatch):
    """审查中危: 框架异常（非 command_runner 路径）→ error 字段非空，不伪造通过.

    回归: 修复前该路径 failed_count=0/failures=() → 调用方误判通过。
    """
    import subprocess
    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=120)
    monkeypatch.setattr(subprocess, "run", _boom)
    # 无 command_runner → 走 subprocess 路径
    g = RegressionGuard(dep_graph=_FakeDepGraph(["tests/test_calc.py"]))
    r = g.verify(["src/calc.py"])
    assert r.error is not None and "超时" in r.error
    assert r.completed is False
    text = r.to_feedback_section()
    assert "[状态: error]" in text and "未完成" in text


def test_runner_oserror_sets_error_field(monkeypatch):
    """框架 OSError → error 字段非空."""
    import subprocess
    def _boom(*a, **kw):
        raise OSError("no such file: pytest")
    monkeypatch.setattr(subprocess, "run", _boom)
    g = RegressionGuard(dep_graph=_FakeDepGraph(["tests/test_calc.py"]))
    r = g.verify(["src/calc.py"])
    assert r.error is not None and "OSError" in r.error
    assert r.completed is False
    assert r.failed_count == 0  # 但 error 非空——调用方不得按 failed_count 判通过
