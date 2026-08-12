"""M51: edit_file 四段式文件修改工具测试."""

from __future__ import annotations

from llm_loop.tools.builtin.edit_file import EditFileTool


def run(args: dict):
    return EditFileTool().run(args)


def test_replace_success_and_verify(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world\nfoo bar\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "foo bar", "new_string": "baz qux"})
    assert r.status.value == "success"
    assert "已校验" in r.content and "+1/-1" in r.content
    assert f.read_text(encoding="utf-8") == "hello world\nbaz qux\n"


def test_no_match_honest_failure(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "不存在的内容", "new_string": "x"})
    assert r.status.value == "error"
    assert r.error_type == "NoMatch"
    assert "read_file" in r.content  # 引导 AI 先读文件拿精确文本
    assert f.read_text(encoding="utf-8") == "hello\n"  # 原状保持


def test_multiple_matches_rejected_by_default(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a=1\na=2\na=3\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "a=", "new_string": "b="})
    assert r.status.value == "error"
    assert r.error_type == "MultipleMatches"
    assert "3 处" in r.content
    assert f.read_text(encoding="utf-8") == "a=1\na=2\na=3\n"  # 未动


def test_replace_all(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("a=1\na=2\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "a=", "new_string": "b=", "replace_all": True})
    assert r.status.value == "success"
    assert "替换 2 处" in r.content
    assert f.read_text(encoding="utf-8") == "b=1\nb=2\n"


def test_dry_run_no_write(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old line\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "old line", "new_string": "new line", "dry_run": True})
    assert r.status.value == "success"
    assert "预览模式" in r.content and "未写入" in r.content
    assert "```diff" in r.content
    assert f.read_text(encoding="utf-8") == "old line\n"  # 未写入


def test_file_not_found(tmp_path):
    r = run({"path": str(tmp_path / "nope.txt"), "old_string": "x", "new_string": "y"})
    assert r.status.value == "error"
    assert r.error_type == "FileNotFoundError"


def test_empty_old_string_rejected(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "", "new_string": "y"})
    assert r.status.value == "error"


def test_missing_params(tmp_path):
    r = run({"path": ""})
    assert r.status.value == "error"


def test_no_tmp_residue_on_success(tmp_path):
    """原子写入成功后目录无 .tmp 残留."""
    f = tmp_path / "a.txt"
    f.write_text("x\n", encoding="utf-8")
    run({"path": str(f), "old_string": "x", "new_string": "y"})
    assert list(tmp_path.glob("*.tmp")) == []


def test_diff_preview_content(tmp_path):
    """回执含统一 diff，+/- 行可见（AI 可自查改动正确性）."""
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    r = run({"path": str(f), "old_string": "line2", "new_string": "LINE2"})
    assert "-line2" in r.content and "+LINE2" in r.content
