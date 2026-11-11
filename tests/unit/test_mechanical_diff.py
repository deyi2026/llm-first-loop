"""EVO-20261111-8c5b88df：切片内机械修复判据（仅注解/纯格式）。

全部机检、fail-closed：任何判不了（语法错误、非 .py、越出切片、语义变化）
都判 not mechanical，走全新审查轮。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_loop.tools.mechanical_diff import assess_mechanical_fix


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "work", ".")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    return r


MOD_SRC = """\
def add(a, b):
    total = a + b
    return total
"""


class TestMechanicalCategories:
    def test_annotation_only_is_mechanical(self, repo):
        old = _commit(repo, {"m.py": MOD_SRC}, "base")
        new = _commit(
            repo,
            {
                "m.py": (
                    "def add(a: int, b: int) -> int:\n"
                    "    total: int = a + b\n"
                    "    return total\n"
                )
            },
            "add type annotations",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["category"] == "annotation_only"
        assert r["changed_paths"] == ["m.py"]

    def test_narrowed_annotation_is_mechanical(self, repo):
        """REPORT §3#7 的原始案例：Any 收窄为具体类型。"""
        old = _commit(
            repo,
            {"m.py": "from typing import Any\n\n\ndef f(x: Any) -> Any:\n    return x\n"},
            "base",
        )
        new = _commit(
            repo,
            {"m.py": "from typing import Any\n\n\ndef f(x: str) -> str:\n    return x\n"},
            "narrow types",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["category"] == "annotation_only"

    def test_format_only_is_mechanical(self, repo):
        old = _commit(repo, {"m.py": "def f( x,y ):\n    return  x+y\n"}, "base")
        new = _commit(repo, {"m.py": "def f(x, y):\n    return x + y\n"}, "black")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["category"] == "format_only"


class TestShouldRefuse:
    def test_control_flow_change_not_mechanical(self, repo):
        """RULE-AI-35 应拦实测：语义变化必须判 not mechanical。"""
        old = _commit(repo, {"m.py": MOD_SRC}, "base")
        new = _commit(
            repo,
            {"m.py": "def add(a, b):\n    if a < 0:\n        return 0\n    total = a + b\n    return total\n"},
            "real logic change",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False
        assert "semantic" in r["reason"]

    def test_literal_change_not_mechanical(self, repo):
        old = _commit(repo, {"m.py": "LIMIT = 10\n"}, "base")
        new = _commit(repo, {"m.py": "LIMIT = 100\n"}, "change limit")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False

    def test_signature_param_change_not_mechanical(self, repo):
        """签名变化（参数默认值）不是机械修复。"""
        old = _commit(repo, {"m.py": "def f(a, b=1):\n    return a + b\n"}, "base")
        new = _commit(repo, {"m.py": "def f(a, b=2):\n    return a + b\n"}, "default")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False

    def test_new_statement_not_mechanical(self, repo):
        old = _commit(repo, {"m.py": MOD_SRC}, "base")
        new = _commit(repo, {"m.py": MOD_SRC + "\n\ndef g():\n    return 1\n"}, "add fn")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False

    def test_non_python_file_not_mechanical(self, repo):
        old = _commit(repo, {"m.py": MOD_SRC, "cfg.toml": "a = 1\n"}, "base")
        new = _commit(repo, {"m.py": MOD_SRC, "cfg.toml": "a = 2\n"}, "toml change")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False
        assert "non_python" in r["reason"]

    def test_syntax_error_fail_closed(self, repo):
        old = _commit(repo, {"m.py": MOD_SRC}, "base")
        (repo / "m.py").write_text("def broken(:\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "broken")
        new = _git(repo, "rev-parse", "HEAD")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False
        assert "fail_closed" in r["reason"]

    def test_outside_slice_not_mechanical(self, repo):
        old = _commit(repo, {"in_slice.py": MOD_SRC, "out.py": "x = 1\n"}, "base")
        new = _commit(
            repo,
            {
                "in_slice.py": "def add(a: int, b: int) -> int:\n    total = a + b\n    return total\n",
                "out.py": "x = 2\n",
            },
            "touch outside",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new, allowed_paths=["in_slice.py"])
        assert r["mechanical"] is False
        assert "outside_slice" in r["reason"]

    def test_bad_ref_fail_closed(self, repo):
        old = _commit(repo, {"m.py": MOD_SRC}, "base")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha="0" * 40)
        assert r["mechanical"] is False
        assert "fail_closed" in r["reason"]


class TestMixedMechanical:
    def test_mixed_files_categorized(self, repo):
        """两文件都是机械（一格式一注解）⇒ mechanical，逐文件类别。"""
        old = _commit(
            repo,
            {"a.py": "def f( x ):\n    return x\n", "b.py": "def g(v):\n    return v\n"},
            "base",
        )
        new = _commit(
            repo,
            {
                "a.py": "def f(x):\n    return x\n",
                "b.py": "def g(v: int) -> int:\n    return v\n",
            },
            "mechanical both",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["per_file"]["a.py"] == "format_only"
        assert r["per_file"]["b.py"] == "annotation_only"


class TestEagerAnnotationSafetyGate:
    """审查 P1（2026-11-11）：无 future import 时注解在 import/def 时急切求值。"""

    def test_callable_annotation_refused(self, repo):
        """注解含 Call（import 时执行）⇒ not mechanical（应拦核心）。"""
        old = _commit(repo, {"m.py": "def f(x):\n    return x\n"}, "base")
        new = _commit(repo, {"m.py": "def f(x: make_ann()):\n    return x\n"}, "call ann")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False
        assert "eager_annotation_risk" in r["reason"]

    def test_unknown_name_annotation_refused(self, repo):
        """注解引用未知名字（import 时 NameError 风险）⇒ not mechanical。"""
        old = _commit(repo, {"m.py": "def f(x):\n    return x\n"}, "base")
        new = _commit(repo, {"m.py": "def f(x: NewType):\n    return x\n"}, "unknown name")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is False
        assert "eager_annotation_risk" in r["reason"]

    def test_future_import_makes_any_annotation_safe(self, repo):
        """from __future__ import annotations ⇒ 注解惰性化，变化安全。"""
        src_old = (
            "from __future__ import annotations\n"
            "from typing import Any\n\n\n"
            "def f(x: Any) -> Any:\n    return x\n"
        )
        src_new = (
            "from __future__ import annotations\n"
            "from typing import Any\n\n\n"
            "def f(x: str | None) -> str:\n    return x\n"
        )
        old = _commit(repo, {"m.py": src_old}, "base")
        new = _commit(repo, {"m.py": src_new}, "lazy ann")
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["category"] == "annotation_only"

    def test_builtin_and_imported_names_accepted(self, repo):
        """内建类型名 + 已 import 名字（Any→str）⇒ 安全（原 REPORT 案例）。"""
        old = _commit(
            repo,
            {"m.py": "from typing import Any\n\n\ndef f(x: Any) -> Any:\n    return x\n"},
            "base",
        )
        new = _commit(
            repo,
            {"m.py": "from typing import Any\n\n\ndef f(x: str) -> str:\n    return x\n"},
            "narrow",
        )
        r = assess_mechanical_fix(repo, old_sha=old, new_sha=new)
        assert r["mechanical"] is True
        assert r["category"] == "annotation_only"
