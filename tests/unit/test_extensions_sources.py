"""P2-B 安装源：Git/归档获取与安全解压（设计 §5.2 / FR-12）.

- Git：分支/tag 解析固定到具体 commit；坏 ref/非空目标如实拒绝。
- 归档：zip/tar 安全解压（越界/symlink/硬链接/设备/重复/上限拒绝）；
  digest 钉扎校验；单顶层目录解包。
- 完整性 ≠ 真实性：digest 只证明完整性，元数据明示不声称真实性。
- install_fetched：源 locator 记入 InstallRecord.source；临时目录清理。
"""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from llm_loop.extensions.sources import (
    SourceRejectedError,
    fetch_archive_source,
    fetch_git_source,
    install_fetched,
)
from llm_loop.extensions.store import ExtensionStore


def _make_git_repo(path: Path) -> None:
    (path / ".claude-plugin").mkdir(parents=True)
    (path / ".claude-plugin/plugin.json").write_text(
        json.dumps({"name": "gitpkg", "version": "1.0.0"})
    )
    (path / "skills").mkdir()
    (path / "skills/gitpkg.md").write_text("---\nname: gitpkg\ndescription: from git\n---\nbody")

    def g(*args: str) -> None:
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    g("init", "-q")
    g("add", "-A")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    g("tag", "v1")


def test_git_source_pins_ref_to_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_git_repo(repo)
    dest = tmp_path / "g1"
    fetched = fetch_git_source(f"file://{repo}", ref="v1", dest=dest)
    assert fetched.locator.startswith(f"git+file://{repo}@")
    # commit 为 40 hex
    commit = fetched.locator.rsplit("@", 1)[1]
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    # 内容落地且 plugin.json 可读（未执行任何脚本）
    assert json.loads((fetched.root / ".claude-plugin/plugin.json").read_text())["name"] == "gitpkg"
    assert fetched.fetch_meta["requested_ref"] == "v1"
    assert fetched.fetch_meta["submodules"] == "disabled"


def test_git_source_rejects_bad_ref_and_dirty_dest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_git_repo(repo)
    with pytest.raises(SourceRejectedError, match="fetch 失败|no-such-ref"):
        fetch_git_source(f"file://{repo}", ref="no-such-ref", dest=tmp_path / "g1")
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "x.txt").write_text("x")
    with pytest.raises(SourceRejectedError, match="目标目录非空"):
        fetch_git_source(f"file://{repo}", ref="v1", dest=dirty)


def _zip_bytes(entries: list[tuple[str, str | bytes]], symlinks: list[tuple[str, str]] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        for name, target in symlinks or []:
            info = zipfile.ZipInfo(name)
            info.create_system = 3  # unix
            info.external_attr = (0o120777 << 16)  # symlink
            zf.writestr(info, target)
    return buf.getvalue()


def test_archive_zip_happy_path_with_unwrap(tmp_path: Path) -> None:
    arc = tmp_path / "pkg.zip"
    arc.write_bytes(
        _zip_bytes(
            [
                ("pkg/.claude-plugin/plugin.json", json.dumps({"name": "arcpkg", "version": "2.0"})),
                ("pkg/skills/arcpkg.md", "---\nname: arcpkg\ndescription: z\n---\nx"),
            ]
        )
    )
    fetched = fetch_archive_source(str(arc))
    assert fetched.fetch_meta["unwrapped_top_dir"] == "pkg"
    assert (fetched.root / ".claude-plugin/plugin.json").exists()
    assert fetched.locator.startswith("archive:")
    assert "sha256=" in fetched.locator or "#sha256=" in fetched.locator
    # 完整性 ≠ 真实性：如实分开表述
    assert "not-claimed" in json.dumps(fetched.fetch_meta, ensure_ascii=False) or any(
        "真实性" in str(v) for v in fetched.fetch_meta.values()
    )


def test_archive_digest_pinning(tmp_path: Path) -> None:
    arc = tmp_path / "pkg.zip"
    arc.write_bytes(_zip_bytes([("p/plugin.json", "{}")]))
    fetched = fetch_archive_source(str(arc))
    pinned = fetch_archive_source(str(arc), expected_sha256=fetched.integrity)
    assert pinned.integrity == fetched.integrity
    with pytest.raises(SourceRejectedError, match="digest 不匹配"):
        fetch_archive_source(str(arc), expected_sha256="0" * 64)


def test_archive_rejects_zip_slip_symlink_duplicate_and_absolute(tmp_path: Path) -> None:
    slip = tmp_path / "slip.zip"
    slip.write_bytes(_zip_bytes([("../evil.txt", "x")]))
    with pytest.raises(SourceRejectedError, match=r"\.\./|越界"):
        fetch_archive_source(str(slip))

    sym = tmp_path / "sym.zip"
    sym.write_bytes(_zip_bytes([("a.txt", "ok")], symlinks=[("lnk", "/etc/passwd")]))
    with pytest.raises(SourceRejectedError, match="symlink"):
        fetch_archive_source(str(sym))

    dup_buf = io.BytesIO()
    with zipfile.ZipFile(dup_buf, "w") as zf:
        zf.writestr("a.txt", "1")
        zf.writestr("a.txt", "2")
    dup = tmp_path / "dup.zip"
    dup.write_bytes(dup_buf.getvalue())
    with pytest.raises(SourceRejectedError, match="重复条目"):
        fetch_archive_source(str(dup))

    import tarfile

    abs_buf = io.BytesIO()
    with tarfile.open(fileobj=abs_buf, mode="w") as tf:
        data = b"x"
        ti = tarfile.TarInfo("/abs/evil.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    absarc = tmp_path / "abs.tar"
    absarc.write_bytes(abs_buf.getvalue())
    with pytest.raises(SourceRejectedError, match="绝对路径"):
        fetch_archive_source(str(absarc))


def test_archive_rejects_tar_symlink_hardlink_and_device(tmp_path: Path) -> None:
    import tarfile

    def build(members) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for name, kind, linkname in members:
                ti = tarfile.TarInfo(name)
                if kind == "sym":
                    ti.type = tarfile.SYMTYPE
                    ti.linkname = linkname
                    tf.addfile(ti)
                elif kind == "lnk":
                    ti.type = tarfile.LNKTYPE
                    ti.linkname = linkname
                    tf.addfile(ti)
                elif kind == "fifo":
                    ti.type = tarfile.FIFOTYPE
                    tf.addfile(ti)
                else:
                    ti.size = 1
                    tf.addfile(ti, io.BytesIO(b"x"))
        return buf.getvalue()

    for members, match in (
        ([("lnk", "sym", "target")], "symlink/硬链接"),
        ([("hard", "lnk", "target")], "symlink/硬链接"),
        ([("fifo", "fifo", "")], "设备/FIFO"),
    ):
        arc = tmp_path / f"tar-{members[0][0]}.tar"
        arc.write_bytes(build(members))
        with pytest.raises(SourceRejectedError, match=match):
            fetch_archive_source(str(arc))


def test_archive_size_and_entry_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import llm_loop.extensions.sources as sources

    # 大小上限：归档字节数超限（本地文件侧）
    big = tmp_path / "big.zip"
    big.write_bytes(_zip_bytes([("pkg/a.bin", b"\0" * 4096)]))
    monkeypatch.setattr(sources, "MAX_ARCHIVE_BYTES", 1024)
    with pytest.raises(SourceRejectedError, match="大小上限"):
        fetch_archive_source(str(big))
    # 条目上限
    monkeypatch.setattr(sources, "MAX_ARCHIVE_BYTES", 64 * 1024 * 1024)
    many = tmp_path / "many.zip"
    many.write_bytes(_zip_bytes([(f"pkg/f{i}.txt", "x") for i in range(8)]))
    monkeypatch.setattr(sources, "MAX_ARCHIVE_ENTRIES", 4)
    with pytest.raises(SourceRejectedError, match="条目超过"):
        fetch_archive_source(str(many))


def test_install_fetched_records_locator(tmp_path: Path) -> None:
    arc = tmp_path / "pkg.zip"
    arc.write_bytes(
        _zip_bytes(
            [
                ("pkg/plugin.json", json.dumps({"name": "arcpkg", "schema_version": "1.0.0", "version": "9.9"})),
                ("pkg/skills/deploy/SKILL.md", "---\nname: deploy\ndescription: d\n---\nbody"),
            ]
        )
    )
    fetched = fetch_archive_source(str(arc))
    root = fetched.root
    store = ExtensionStore(tmp_path / "store")
    record = install_fetched(store, fetched, scopes=["session"])
    assert record.source == fetched.locator
    assert not root.exists()  # 临时目录清理
    assert (tmp_path / "store").exists()
