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


# ── EVO-20260814-aab7eb0b P1: 归一化 + 基线校验 ──


def test_crlf_file_preserved_and_lf_oldstring_matches(tmp_path):
    """CRLF 文件：LF 风格 old_string 应能匹配，写回后保持 CRLF。"""
    f = tmp_path / "win.txt"
    f.write_bytes(b"line one\r\nline two\r\nline three\r\n")
    r = run({"path": str(f), "old_string": "line two", "new_string": "LINE TWO"})
    assert r.status.value == "success"
    assert "CRLF" in r.content  # 如实标注已保留原换行风格
    assert f.read_bytes() == b"line one\r\nLINE TWO\r\nline three\r\n"


def test_bom_preserved(tmp_path):
    """UTF-8 BOM 文件：替换后 BOM 保留且如实标注。"""
    f = tmp_path / "bom.txt"
    f.write_bytes(b"\xef\xbb\xbfhello\nworld\n")
    r = run({"path": str(f), "old_string": "world", "new_string": "there"})
    assert r.status.value == "success"
    assert "BOM" in r.content
    assert f.read_bytes() == b"\xef\xbb\xbfhello\nthere\n"


def test_crlf_oldstring_matches_lf_file(tmp_path):
    """反向：CRLF 风格 old_string 匹配 LF 文件（跨平台粘贴场景）。"""
    f = tmp_path / "unix.txt"
    f.write_bytes(b"alpha\nbeta\ngamma\n")
    r = run({"path": str(f), "old_string": "beta\r\ngamma", "new_string": "B\nG"})
    assert r.status.value == "success"
    assert f.read_bytes() == b"alpha\nB\nG\n"


def test_baseline_change_rejected(tmp_path, monkeypatch):
    """匹配后、写入前文件被外部修改 → 拒绝写入（BaselineChanged），文件保持外部修改后的状态。"""
    from llm_loop.tools.builtin import edit_file as mod

    f = tmp_path / "race.txt"
    f.write_text("original\n", encoding="utf-8")

    real_baseline = mod.EditFileTool._baseline
    calls = {"n": 0}

    def racing_baseline(path):
        calls["n"] += 1
        if calls["n"] == 2:  # 写入前第二次校验时模拟外部改动
            f.write_text("externally modified\n", encoding="utf-8")
        return real_baseline(path)

    monkeypatch.setattr(mod.EditFileTool, "_baseline", staticmethod(racing_baseline))
    r = run({"path": str(f), "old_string": "original", "new_string": "mine"})
    assert r.status.value == "error"
    assert r.error_type == "BaselineChanged"
    assert f.read_text(encoding="utf-8") == "externally modified\n"  # 未覆盖外部改动
