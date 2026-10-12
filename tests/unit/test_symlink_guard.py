"""T5b(2026-08-14) symlink 防护测试（零 LLM 零网络）+ R9-IMM-04 三态化.

覆盖: link_shaped_paths 三态探测（no_links / links_found / probe_failed；
无链接/自身链接/父目录链接/不存在路径/ELOOP 循环链/探测异常）/
read_file 读 symlink 如实标注不拒绝 / edit_file 写 symlink 拒绝（自身/父目录）/
ELOOP 拒写且错误信息区分"探测失败"与"存在符号链接"（R9-DFX-05）/
无 symlink 零回归 / 路径不存在时父链检测（写场景）。
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.safety import LinkProbeResult, link_shaped_paths


def _read(path: str):
    return ReadFileTool().execute(path=path)


def _edit(path: str, old: str = "a", new: str = "b"):
    return EditFileTool().execute(path=path, old_string=old, new_string=new)


# ── link_shaped_paths 纯函数（三态断言，R9-IMM-04）──


def test_no_symlink_empty(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("x", encoding="utf-8")
    assert link_shaped_paths(f) == LinkProbeResult(status="no_links")
    assert link_shaped_paths(tmp_path).status == "no_links"


def test_self_symlink_detected(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    result = link_shaped_paths(link)
    assert result.status == "links_found"
    assert result.links == (str(link),)


def test_parent_dir_symlink_detected(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "f.txt").write_text("x", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    result = link_shaped_paths(link_dir / "f.txt")
    assert result.status == "links_found"
    assert result.links == (str(link_dir),)


def test_missing_path_via_symlink_parent(tmp_path):
    """写场景：待建文件不存在，但父目录是 symlink → 检测到."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    result = link_shaped_paths(link_dir / "not_yet.txt")
    assert result.status == "links_found"
    assert result.links == (str(link_dir),)


def test_missing_path_no_symlink_empty(tmp_path):
    assert link_shaped_paths(tmp_path / "plain" / "not_yet.txt").status == "no_links"


def test_eloop_chain_detected(tmp_path):
    """ELOOP 循环链：macOS/Linux 下循环组件可被 is_symlink 检出 → links_found."""
    l1, l2 = tmp_path / "loop1", tmp_path / "loop2"
    l1.symlink_to(l2)
    l2.symlink_to(l1)
    result = link_shaped_paths(l1 / "deep" / "file.txt")
    # 探测必然异常或检出链——两种出口都不得是 no_links（防护不静默失效）
    assert result.status in ("links_found", "probe_failed")


def test_probe_failed_on_oserror(tmp_path, monkeypatch):
    """探测抛 OSError（如 ELOOP stat 障碍）→ probe_failed（fail-open 不抛异常）."""

    def _raise(self):
        raise OSError(errno.ELOOP, "too many levels of symbolic links")

    monkeypatch.setattr(Path, "is_symlink", _raise)
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    result = link_shaped_paths(f)
    assert result.status == "probe_failed"
    assert result.links == ()


def test_frozen_dataclass_immutable():
    import dataclasses

    r = LinkProbeResult(status="no_links")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.status = "links_found"  # type: ignore[misc]


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


def test_read_probe_failed_annotates_not_blocks(tmp_path, monkeypatch):
    """读面 probe_failed：透明标注、不拒读（探测结果透传，不扩大拒读）."""

    def _raise(self):
        raise OSError(errno.ELOOP, "too many levels of symbolic links")

    monkeypatch.setattr(Path, "is_symlink", _raise)
    f = tmp_path / "plain2.txt"
    f.write_text("content-ok", encoding="utf-8")
    r = _read(str(f))
    assert r.status.value == "success"
    assert "content-ok" in r.content
    assert "探测失败" in r.content


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


def test_edit_eloop_rejected(tmp_path):
    """R9-DFX-05 验收面：ELOOP 场景调用 edit_file → 拒绝写入."""
    l1, l2 = tmp_path / "loop1", tmp_path / "loop2"
    l1.symlink_to(l2)
    l2.symlink_to(l1)
    r = _edit(str(l1 / "deep" / "file.txt"))
    assert r.status.value in ("error", "failure", "blocked")
    # 两种出口之一，且信息可区分（links_found→"含符号链接"；probe_failed→"探测失败"）
    assert ("符号链接" in r.content) or ("探测失败" in r.content)


def test_edit_probe_failed_rejected_with_distinct_message(tmp_path, monkeypatch):
    """探测失败（probe_failed）→ 拒写，错误信息与"存在符号链接"明确区分（R9-DFX-05）."""

    def _raise(self):
        raise OSError(errno.ELOOP, "too many levels of symbolic links")

    monkeypatch.setattr(Path, "is_symlink", _raise)
    f = tmp_path / "w.txt"
    f.write_text("a", encoding="utf-8")
    r = _edit(str(f))
    assert r.status.value in ("error", "failure", "blocked")
    assert "探测失败" in r.content
    assert "无法确认路径安全性" in r.content
    assert f.read_text(encoding="utf-8") == "a"  # 未被写入


def test_edit_links_found_message_distinct(tmp_path):
    """存在链接拒写信息与探测失败信息可区分（对照面）."""
    target = tmp_path / "t.txt"
    target.write_text("a", encoding="utf-8")
    link = tmp_path / "l.txt"
    link.symlink_to(target)
    r = _edit(str(link))
    assert "写路径含符号链接" in r.content
    assert "探测失败" not in r.content


def test_edit_plain_zero_regression(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("a", encoding="utf-8")
    r = _edit(str(f))
    assert r.status.value == "success"
    assert f.read_text(encoding="utf-8") == "b"
