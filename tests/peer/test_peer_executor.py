"""执行器首切片：fs.read / fs.list 的字节保真、截断、越界与未实现 kind。"""
from __future__ import annotations

import json

import pytest

from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.errors import PeerError
from llm_loop.peer.executor import MAX_LIST_ENTRIES, Executor


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    return root, Executor(artifacts=ArtifactStore(tmp_path / "artifacts"), node_id="deepin-01")


def test_fs_read_returns_artifact_not_inline_bytes(tmp_path, env):
    root, ex = env
    payload = b"line-1\nline-2\n"
    (root / "a.txt").write_bytes(payload)
    out = ex.run(kind="fs.read", params={"path": str(root / "a.txt")}, allowed_paths=(str(root),))
    assert len(out.artifacts) == 1
    ref = out.artifacts[0]["ref"]
    assert out.artifacts[0]["bytes"] == len(payload)
    assert "line-1" not in out.summary and ref not in out.summary
    stored = ArtifactStore(tmp_path / "artifacts").read(ref)
    assert stored == payload


def test_fs_read_truncates_at_max_bytes(tmp_path, env):
    root, ex = env
    (root / "big.bin").write_bytes(b"x" * 100)
    out = ex.run(
        kind="fs.read",
        params={"path": str(root / "big.bin"), "max_bytes": 10},
        allowed_paths=(str(root),),
    )
    assert out.artifacts[0]["bytes"] == 10
    assert "truncated" in out.summary


def test_fs_read_outside_allowed_paths_is_gate3_denial(tmp_path, env):
    root, ex = env
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    with pytest.raises(PeerError) as err:
        ex.run(kind="fs.read", params={"path": str(outside)}, allowed_paths=(str(root),))
    assert err.value.reason_code == "path_outside_allowed_paths"


def test_fs_read_directory_rejected(tmp_path, env):
    root, ex = env
    with pytest.raises(PeerError) as err:
        ex.run(kind="fs.read", params={"path": str(root)}, allowed_paths=(str(root),))
    assert err.value.reason_code == "params_schema_invalid"


def test_fs_list_reports_entries_without_following_dir_symlinks(tmp_path, env):
    root, ex = env
    (root / "a.txt").write_text("a")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("bb")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (root / "link").symlink_to(outside)

    out = ex.run(kind="fs.list", params={"path": str(root), "depth": 2}, allowed_paths=(str(root),))
    listing = json.loads(ArtifactStore(tmp_path / "artifacts").read(out.artifacts[0]["ref"]))
    names = {e["name"] for e in listing["entries"]}
    assert {"a.txt", "sub", "link", "b.txt"} <= names
    assert "secret.txt" not in names
    assert listing["truncated"] is False


def test_fs_list_depth_one_does_not_descend(tmp_path, env):
    root, ex = env
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("d")
    out = ex.run(kind="fs.list", params={"path": str(root), "depth": 1}, allowed_paths=(str(root),))
    listing = json.loads(ArtifactStore(tmp_path / "artifacts").read(out.artifacts[0]["ref"]))
    assert {e["name"] for e in listing["entries"]} == {"sub"}


def test_fs_list_entry_cap(tmp_path, env):
    root, ex = env
    for i in range(MAX_LIST_ENTRIES + 20):
        (root / f"f{i:04d}.txt").write_text("x")
    out = ex.run(kind="fs.list", params={"path": str(root)}, allowed_paths=(str(root),))
    listing = json.loads(ArtifactStore(tmp_path / "artifacts").read(out.artifacts[0]["ref"]))
    assert len(listing["entries"]) == MAX_LIST_ENTRIES
    assert listing["truncated"] is True


@pytest.mark.parametrize("kind", ["fs.write", "shell.exec", "desktop.screenshot", "desktop.click"])
def test_unimplemented_kinds_refuse_loudly(tmp_path, env, kind):
    _root, ex = env
    with pytest.raises(PeerError) as err:
        ex.run(kind=kind, params={}, allowed_paths=(str(tmp_path),))
    assert err.value.reason_code == "policy_task_kind_not_allowed"
    assert "handler_missing" in err.value.detail
