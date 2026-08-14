"""T5b(2026-08-14) symlink 防护测试（零 LLM 零网络）.

覆盖: link_shaped_paths 纯函数（无链接/自身链接/父目录链接/不存在路径）/
read_file 读 symlink 如实标注不拒绝 / edit_file 写 symlink 拒绝（自身/父目录）/
无 symlink 零回归 / 路径不存在时父链检测（写场景）。
"""

from __future__ import annotations

from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.safety import link_shaped_paths


def _read(path: str):
    return ReadFileTool().execute(path=path)


def _edit(path: str, old: str = "a", new: str = "b"):
    return EditFileTool().execute(path=path, old_string=old, new_string=new)


# ── link_shaped_paths 纯函数 ──


def test_no_symlink_empty(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("x", encoding="utf-8")
    assert link_shaped_paths(f) == []
    assert link_shaped_paths(tmp_path) == []


def test_self_symlink_detected(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert link_shaped_paths(link) == [str(link)]


def test_parent_dir_symlink_detected(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "f.txt").write_text("x", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    result = link_shaped_paths(link_dir / "f.txt")
    assert result == [str(link_dir)]


def test_missing_path_via_symlink_parent(tmp_path):
    """写场景：待建文件不存在，但父目录是 symlink → 检测到."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    result = link_shaped_paths(link_dir / "not_yet.txt")
    assert result == [str(link_dir)]


def test_missing_path_no_symlink_empty(tmp_path):
    assert link_shaped_paths(tmp_path / "plain" / "not_yet.txt") == []


# ── read_file：标注不拒绝 ──


def test_read_symlink_annotates_but_reads(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("hello symlink", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    r = _read(str(link))
    assert r.status.value == "success"
    assert "hello symlink" in r.content
    assert "[symlink]" in r.content
    assert str(link) in r.content


def test_read_plain_no_annotation(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("plain", encoding="utf-8")
    r = _read(str(f))
    assert r.status.value == "success"
    assert "[symlink]" not in r.content


# ── edit_file：写 symlink 拒绝（fail-closed）──


def test_edit_self_symlink_rejected(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("a", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    r = _edit(str(link))
    assert r.status.value in ("error", "failure", "blocked")
    assert "符号链接" in r.content
    assert target.read_text(encoding="utf-8") == "a"  # 目标未被修改


def test_edit_parent_symlink_rejected(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "f.txt").write_text("a", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    r = _edit(str(link_dir / "f.txt"))
    assert r.status.value in ("error", "failure", "blocked")
    assert "符号链接" in r.content
    assert (real_dir / "f.txt").read_text(encoding="utf-8") == "a"


def test_edit_plain_zero_regression(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("a", encoding="utf-8")
    r = _edit(str(f))
    assert r.status.value == "success"
    assert f.read_text(encoding="utf-8") == "b"
