"""T9-a 写侧：闸4 写域门 + fs.write 执行器。

口径（对齐 DESIGN §5.5「闸3 与闸4 各自独立拒绝」）：
- 闸4 拒绝的输入必须**真的被拒**，且错误码/细节可判定（RULE-AI-35）；
- 闸3 与闸4 互不替代：域外但租约内 → sandbox_denied；租约外但域内 → path_outside_allowed_paths；
- 写域未配置 = 全拒（fail-closed），不从租约推导默认值。
"""

from __future__ import annotations

import base64
import hashlib
import os

import pytest

from llm_loop.peer.artifacts import ArtifactStore
from llm_loop.peer.errors import PeerError
from llm_loop.peer.executor import MAX_WRITE_BYTES, Executor
from llm_loop.peer.write_gate import require_write_target


def _err(exc_info) -> tuple[str, str]:
    err = exc_info.value
    return err.reason_code, err.detail


def test_write_root_unset_denies_everything(tmp_path):
    """未注入写域根 = 全拒；不从 grant 或进程环境推导默认值。"""
    with pytest.raises(PeerError) as err:
        require_write_target(str(tmp_path / "a.txt"))
    assert _err(err) == ("sandbox_denied", "write_root_not_configured:LFL_PEER_WRITE_ROOT")


def test_write_gate_ignores_process_env(tmp_path, monkeypatch):
    """策略层已不读进程环境：设了 env 也不生效，只有显式注入才放行（防回落回潮）。"""
    monkeypatch.setenv("LFL_PEER_WRITE_ROOT", str(tmp_path))
    with pytest.raises(PeerError) as err:
        require_write_target(str(tmp_path / "a.txt"))
    assert _err(err)[1].startswith("write_root_not_configured")
    assert require_write_target(
        str(tmp_path / "a.txt"), write_root=str(tmp_path)
    ) == os.path.realpath(tmp_path / "a.txt")


def test_write_root_relative_is_denied(tmp_path):
    with pytest.raises(PeerError) as err:
        require_write_target(str(tmp_path / "a.txt"), write_root="relative/dir")
    code, detail = _err(err)
    assert code == "sandbox_denied" and "must_be_absolute" in detail


def test_write_root_injected_is_used(tmp_path):
    assert require_write_target(
        str(tmp_path / "a.txt"), write_root=str(tmp_path)
    ) == os.path.realpath(tmp_path / "a.txt")


def test_target_parent_outside_write_root_denied(tmp_path):
    root = tmp_path / "wr"
    root.mkdir()
    with pytest.raises(PeerError) as err:
        require_write_target(str(tmp_path / "elsewhere" / "a.txt"), write_root=str(root))
    code, detail = _err(err)
    assert code == "sandbox_denied" and "outside_peer_write_root" in detail


def test_lookalike_prefix_is_not_a_child(tmp_path):
    """``/wr-evil`` 不是 ``/wr`` 的子目录：按分隔符边界判，不按字符串前缀。"""
    root = tmp_path / "wr"
    evil = tmp_path / "wr-evil"
    root.mkdir()
    evil.mkdir()
    with pytest.raises(PeerError) as err:
        require_write_target(str(evil / "a.txt"), write_root=str(root))
    assert _err(err)[0] == "sandbox_denied"


def test_target_that_is_symlink_is_denied_and_link_not_followed(tmp_path):
    root = tmp_path / "wr"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(outside)

    with pytest.raises(PeerError) as err:
        require_write_target(str(link), write_root=str(root))
    assert _err(err) == ("sandbox_denied", "target_is_symlink")
    assert outside.read_text(encoding="utf-8") == "original"


def test_intermediate_symlink_escaping_root_is_denied(tmp_path):
    root = tmp_path / "wr"
    root.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (root / "jump").symlink_to(outside_dir)
    with pytest.raises(PeerError) as err:
        require_write_target(str(root / "jump" / "a.txt"), write_root=str(root))
    assert _err(err)[0] == "sandbox_denied"


def test_sensitive_path_inside_write_root_is_denied(tmp_path):
    root = tmp_path / "wr"
    (root / ".ssh").mkdir(parents=True)
    with pytest.raises(PeerError) as err:
        require_write_target(str(root / ".ssh" / "authorized_keys"), write_root=str(root))
    assert _err(err) == ("sandbox_denied", "sensitive_path")


def test_sealed_path_denies_even_inside_write_root(tmp_path, monkeypatch):
    """封条由 write_gate 自身判定，不依赖闸3：远程改写 held-out 材料必须拒。"""
    from llm_loop.peer import write_gate

    root = tmp_path / "wr"
    root.mkdir()
    monkeypatch.setattr(write_gate, "sealed_path_reason", lambda _p: "under sealed root")
    with pytest.raises(PeerError) as err:
        require_write_target(str(root / "a.txt"), write_root=str(root))
    code, detail = _err(err)
    assert code == "sandbox_denied" and detail.startswith("sealed_path:")


def test_relative_or_empty_path_is_schema_invalid(tmp_path):
    for bad in ("", "rel/a.txt", None, 123):
        with pytest.raises(PeerError) as err:
            require_write_target(bad, write_root=str(tmp_path))
        assert _err(err)[0] == "params_schema_invalid"


# --- executor ---------------------------------------------------------------


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "wr"
    root.mkdir()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    return root, artifacts, Executor(artifacts=artifacts, node_id="deepin-01", write_root=str(root))


def test_fs_write_writes_bytes_and_reports_digest_not_content(tmp_path, env):
    root, _artifacts, ex = env
    payload = "hello-世界\n".encode()
    out = ex.run(
        kind="fs.write",
        params={"path": str(root / "a.txt"), "content_b64": base64.b64encode(payload).decode()},
        allowed_paths=(str(root),),
    )
    assert (root / "a.txt").read_bytes() == payload
    assert out.artifacts == ()
    assert hashlib.sha256(payload).hexdigest() in out.summary
    assert "hello" not in out.summary


def test_fs_write_from_artifact_ref(tmp_path, env):
    root, artifacts, ex = env
    payload = b"from-artifact"
    ref = artifacts.put(payload, media_type="text/plain")["ref"]
    ex.run(
        kind="fs.write",
        params={"path": str(root / "b.txt"), "artifact_ref": ref},
        allowed_paths=(str(root),),
    )
    assert (root / "b.txt").read_bytes() == payload


def test_fs_write_refuses_existing_target_without_overwrite(tmp_path, env):
    root, _artifacts, ex = env
    (root / "a.txt").write_text("old", encoding="utf-8")
    with pytest.raises(PeerError) as err:
        ex.run(
            kind="fs.write",
            params={"path": str(root / "a.txt"), "content_b64": "bmV3"},
            allowed_paths=(str(root),),
        )
    assert _err(err) == ("params_schema_invalid", "target exists and overwrite=false")
    assert (root / "a.txt").read_text(encoding="utf-8") == "old"


def test_fs_write_overwrite_true_replaces(tmp_path, env):
    root, _artifacts, ex = env
    (root / "a.txt").write_text("old", encoding="utf-8")
    ex.run(
        kind="fs.write",
        params={"path": str(root / "a.txt"), "content_b64": "bmV3", "overwrite": True},
        allowed_paths=(str(root),),
    )
    assert (root / "a.txt").read_text(encoding="utf-8") == "new"


def test_fs_write_bad_base64_is_schema_invalid(tmp_path, env):
    root, _artifacts, ex = env
    with pytest.raises(PeerError) as err:
        ex.run(
            kind="fs.write",
            params={"path": str(root / "a.txt"), "content_b64": "not base64!!"},
            allowed_paths=(str(root),),
        )
    assert _err(err)[0] == "params_schema_invalid"


def test_fs_write_oversize_is_schema_invalid(tmp_path, env):
    root, _artifacts, ex = env
    blob = base64.b64encode(b"x" * (MAX_WRITE_BYTES + 1)).decode()
    with pytest.raises(PeerError) as err:
        ex.run(
            kind="fs.write",
            params={"path": str(root / "a.txt"), "content_b64": blob},
            allowed_paths=(str(root),),
        )
    assert _err(err)[0] == "params_schema_invalid"
    assert not (root / "a.txt").exists()


def test_fs_write_create_parents_controls_mkdir(tmp_path, env):
    root, _artifacts, ex = env
    target = root / "deep" / "er" / "a.txt"
    with pytest.raises(PeerError) as err:
        ex.run(
            kind="fs.write",
            params={"path": str(target), "content_b64": "eA=="},
            allowed_paths=(str(root),),
        )
    assert _err(err) == ("params_schema_invalid", "parent directory does not exist")

    ex.run(
        kind="fs.write",
        params={"path": str(target), "content_b64": "eA==", "create_parents": True},
        allowed_paths=(str(root),),
    )
    assert target.read_bytes() == b"x"


def test_gate3_and_gate4_deny_independently(tmp_path, env):
    """闸4 域外（租约内）与闸3 租约外（域内）都必须被各自拒。"""
    root, _artifacts, ex = env
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(PeerError) as gate4:
        ex.run(
            kind="fs.write",
            params={"path": str(other / "a.txt"), "content_b64": "eA=="},
            allowed_paths=(str(root), str(other)),
        )
    assert _err(gate4)[0] == "sandbox_denied"

    with pytest.raises(PeerError) as gate3:
        ex.run(
            kind="fs.write",
            params={"path": str(root / "a.txt"), "content_b64": "eA=="},
            allowed_paths=(str(other),),
        )
    assert _err(gate3)[0] == "path_outside_allowed_paths"
    assert not (root / "a.txt").exists()


def test_fs_write_still_not_advertised():
    """护栏实测（RULE-AI-35）：T9-a 不打开宣告面，manifest 仍不声称可写。"""
    from llm_loop.peer.kinds import EXECUTABLE_KINDS, manifest_kinds

    assert "fs.write" not in EXECUTABLE_KINDS
    assert "fs.write" not in {row["kind"] for row in manifest_kinds()}


def test_fs_write_params_strict_schema():
    from llm_loop.peer.policy import validate_params

    base = {"path": "/tmp/x", "content_b64": "eA=="}
    validate_params("fs.write", dict(base))

    bad_cases = [
        {**base, "artifact_ref": "artifact://v1/" + "0" * 64},
        {"path": "/tmp/x"},
        {**base, "extra": 1},
        {**base, "overwrite": "yes"},
        {"path": "/tmp/x", "artifact_ref": "file:///etc/passwd"},
        {**base, "content_b64": 123},
    ]
    for params in bad_cases:
        with pytest.raises(PeerError) as err:
            validate_params("fs.write", params)
        assert _err(err)[0] == "params_schema_invalid", params


def test_atomic_write_leaves_no_temp_file_on_failure(tmp_path, env, monkeypatch):
    """replace 失败时不留临时文件，且原文件不被截断。"""
    root, _artifacts, ex = env
    target = root / "a.txt"
    target.write_text("old", encoding="utf-8")

    def boom(_src, _dst):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(PeerError) as err:
        ex.run(
            kind="fs.write",
            params={"path": str(target), "content_b64": "bmV3", "overwrite": True},
            allowed_paths=(str(root),),
        )
    assert _err(err)[0] == "sandbox_denied"
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in root.iterdir() if p.name.startswith(".lfl-peer-write-")] == []
