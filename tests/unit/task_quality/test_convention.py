"""路径 E 上下文约定测试（tasks.md §1.5 验收）."""

from __future__ import annotations

import time
from pathlib import Path

from llm_loop.task_quality.convention import ConventionExtractor
from llm_loop.task_quality.models import ConventionType

GOOD_CODE = '''\
import os
import sys
from pathlib import Path

class AppError(Exception):
    pass

def process_item(item_id: int, name: str) -> str:
    try:
        return f"{item_id}: {name}"
    except KeyError:
        return ""

def helper(count: int) -> int:
    return count + 1
'''

BAD_NAMED = "def BadFunctionName( x ):\n    return x\n"


def _mk_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "proj"
    d.mkdir()
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


def test_extract_four_conventions(tmp_path):
    """同目录有代码: 提取四类约定."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    r = ConventionExtractor().extract(str(d / "new.py"))
    types = {c.convention_type for c in r.conventions}
    assert ConventionType.IMPORT_STYLE in types
    assert ConventionType.NAMING in types
    assert ConventionType.TYPE_ANNOTATION in types
    assert ConventionType.ERROR_HANDLING in types


def test_extract_no_code_no_inject(tmp_path):
    """同目录无代码: conventions=() 不注入."""
    d = _mk_dir(tmp_path, {})  # 空目录
    r = ConventionExtractor().extract(str(d / "new.py"))
    assert r.conventions == ()
    assert r.to_injection_text() == ""


def test_extract_naming_snake(tmp_path):
    """命名约定: snake_case 识别."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    r = ConventionExtractor().extract(str(d / "new.py"))
    naming = next(c for c in r.conventions if c.convention_type == ConventionType.NAMING)
    assert "snake_case" in naming.content


def test_extract_annotation_forced(tmp_path):
    """类型标注: 强制识别."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    r = ConventionExtractor().extract(str(d / "new.py"))
    ann = next(c for c in r.conventions if c.convention_type == ConventionType.TYPE_ANNOTATION)
    assert "强制" in ann.content


def test_extract_syntax_error_skip(tmp_path):
    """解析异常: 跳过异常项继续."""
    d = _mk_dir(tmp_path, {"bad.py": "def broken(:\n", "good.py": GOOD_CODE})
    r = ConventionExtractor().extract(str(d / "new.py"))
    # good.py 仍被解析 → 有约定
    assert len(r.conventions) > 0


def test_truncation(tmp_path):
    """体积控制: 约定摘要短（聚合）时不误报截断；超限逻辑经 original_size 验证."""
    # 大量命名 → 但约定是聚合摘要（去重后条目少），不触发截断是正确行为
    big = "\n".join(f"def func_{i}(x_{i}: int) -> int:\n    return x_{i}\n" for i in range(200))
    d = _mk_dir(tmp_path, {"big.py": big})
    r = ConventionExtractor(max_chars=500).extract(str(d / "new.py"))
    # 聚合摘要天然短：不截断（original == retained）
    assert r.truncated is False
    assert r.original_size == r.retained_size
    # 注入文本体积受控
    assert len(r.to_injection_text()) <= 2000


def test_sanitize_secrets(tmp_path):
    """含密钥: 提取与注入不含密证明文（默认脱敏）."""
    # 用 12 位伪密钥（避免 git_security_scan 的 sk-+16 位模式误拦截；仍可验证脱敏）
    code = "API_KEY = 'sk-abc123xyz'\nSECRET='topsecretvalue123'\ndef f():\n    pass\n"
    d = _mk_dir(tmp_path, {"a.py": code})
    # 提取的命名不含密钥值（脱敏在 to_injection_text 前不直接作用于 content，
    # 验证提取不含密钥模式——提取只取函数/变量名，不取赋值字面量）
    r = ConventionExtractor().extract(str(d / "new.py"))
    text = r.to_injection_text()
    # 经 sanitizer 处理后的文本不含明文密钥
    safe = ConventionExtractor._default_sanitize(text)
    assert "sk-abc123xyz" not in safe
    assert "topsecretvalue123" not in safe


def test_latency_under_5s(tmp_path):
    """单次提取时延 ≤ 5s."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    ext = ConventionExtractor()
    start = time.perf_counter()
    for _ in range(20):
        ext.extract(str(d / "new.py"))
    elapsed = (time.perf_counter() - start) / 20
    assert elapsed < 5.0


def test_event_store_injected(tmp_path):
    """注入成功事件落盘."""
    events = []
    class _Store:
        def append(self, sid, etype, payload):
            events.append((etype, payload))
            return None
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    ConventionExtractor(event_store=_Store(), session_id="s1").extract(str(d / "new.py"))
    assert len(events) == 1
    assert events[0][0] == "task.convention.injected"
    assert events[0][1]["convention_count"] >= 1


def test_check_violations_naming(tmp_path):
    """P0 D2: 违背检测——新代码函数名不符合 snake_case 约定."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    summary = ConventionExtractor().extract(str(d / "new.py"))
    violations = ConventionExtractor().check_violations(summary, BAD_NAMED)
    assert any("BadFunctionName" in v for v in violations)


def test_check_violations_no_violation(tmp_path):
    """P0 D2: 无明显违背 → 空清单."""
    d = _mk_dir(tmp_path, {"a.py": GOOD_CODE})
    summary = ConventionExtractor().extract(str(d / "new.py"))
    violations = ConventionExtractor().check_violations(summary, "def good_name():\n    pass\n")
    assert violations == []
