"""路径 H 错误定位测试（tasks.md §1.4 验收：多格式/回退/体积/证据/时延）."""

from __future__ import annotations

import time

from llm_loop.task_quality import models as tq_models
from llm_loop.task_quality.error_locate import ErrorLocator

PYTEST_OUT = """============================= FAILURES =============================
_____________________________ test_add _____________________________
tests/test_math.py:8: in test_add
    assert add(1, 1) == 3
E   assert 2 == 3
=========================== short test summary info ===========================
FAILED tests/test_math.py::test_add - AssertionError: assert 2 == 3
"""

RUFF_OUT = """tests/test_math.py:10:5: E501 Line too long (99 > 88)
tests/test_math.py:12:1: F401 'os' imported but unused
Found 2 errors.
"""

PYRIGHT_OUT = """tests/test_math.py:10:5 - error: Argument of type "int" cannot be assigned to parameter "x" of type "str" (reportArgumentType)
tests/test_math.py:15:3 - error: "x" is not defined (reportUndefinedVariable)
1 error, 0 warnings, 0 informations
"""

TRACE_OUT = """Traceback (most recent call last):
  File "/app/main.py", line 42, in <module>
    main()
  File "/app/main.py", line 35, in main
    process()
KeyError: 'missing_key'
"""

UNKNOWN_OUT = "some random output without failure info"


def test_pytest_parse():
    """pytest 输出: framework=PYTEST + file:line/reason/assert."""
    r = ErrorLocator().locate(PYTEST_OUT)
    assert r.framework == tq_models.TestFramework.PYTEST
    assert r.fallback is False
    assert len(r.failures) >= 1
    f = r.failures[0]
    assert f.file_path == "tests/test_math.py"
    assert f.line_number == 8
    assert "assert" in f.reason or "AssertionError" in f.reason


def test_ruff_parse():
    """ruff 输出: framework=RUFF + file:line:col/code."""
    r = ErrorLocator().locate(RUFF_OUT)
    assert r.framework == tq_models.TestFramework.RUFF
    assert not r.fallback
    assert any("E501" in f.reason for f in r.failures)
    assert r.failures[0].line_number == 10


def test_pyright_parse():
    """pyright 输出: framework=PYRIGHT."""
    r = ErrorLocator().locate(PYRIGHT_OUT)
    assert r.framework == tq_models.TestFramework.PYRIGHT
    assert not r.fallback
    assert any("reportArgumentType" in f.reason for f in r.failures)


def test_generic_trace_parse():
    """通用 stack trace: framework=GENERIC + 帧定位."""
    r = ErrorLocator().locate(TRACE_OUT)
    assert r.framework == tq_models.TestFramework.GENERIC
    assert not r.fallback
    assert any(f.file_path == "/app/main.py" and f.line_number == 42 for f in r.failures)
    assert any("KeyError" in f.reason for f in r.failures)


def test_unknown_fallback():
    """未知格式: 回退原始输出（fallback=True + original_output）."""
    r = ErrorLocator().locate(UNKNOWN_OUT)
    assert r.framework == tq_models.TestFramework.UNKNOWN
    assert r.fallback is True
    assert UNKNOWN_OUT in r.original_output


def test_no_output_no_parse():
    """无输出/太短: 不触发解析."""
    r = ErrorLocator().locate("")
    assert r.fallback is True
    r2 = ErrorLocator().locate("ok")
    assert r2.fallback is True


def test_truncation_keeps_location():
    """体积超限: 截断标注，优先保留失败位置与原因（前部）."""
    # 构造大量失败（每条含长 reason）→ 结构化文本超 max_chars
    many_failures = "\n".join(
        f"FAILED tests/test_{i}.py::test_{i} - AssertionError: "
        f"very long failure reason message number {i} " + "x" * 80
        for i in range(30)
    )
    r = ErrorLocator(max_chars=500).locate(many_failures)
    assert r.truncated is True
    assert r.original_size == len(many_failures)
    assert r.retained_size <= 500
    text = r.to_injection_text()
    assert "test_" in text  # 位置保留（前部）


def test_failure_evidence_in_output():
    """每项 FailureInfo 可在原始输出找到证据（不臆造）."""
    r = ErrorLocator().locate(RUFF_OUT)
    for f in r.failures:
        # 文件路径或错误码出现在原始输出
        assert f.file_path in RUFF_OUT or any(c in RUFF_OUT for c in f.reason[:4])


def test_event_store_parsed():
    """解析成功事件落盘（framework/failure_count/fallback 统计）."""
    events = []
    class _Store:
        def append(self, sid, etype, payload):
            events.append((etype, payload))
            return None
    locator = ErrorLocator(event_store=_Store(), session_id="s1")
    locator.locate(PYTEST_OUT)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "task.error_locate.parsed"
    assert payload["framework"] == "pytest"
    assert payload["failure_count"] >= 1
    assert payload["fallback"] is False


def test_latency_under_2s():
    """单次解析时延 < 2s."""
    locator = ErrorLocator()
    start = time.perf_counter()
    for _ in range(50):
        locator.locate(PYTEST_OUT)
    elapsed = time.perf_counter() - start
    assert elapsed / 50 < 2.0
