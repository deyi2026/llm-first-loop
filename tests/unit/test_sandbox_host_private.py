"""The Host issuer's unreadable private tree stays protected without blocking Tasks."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from llm_loop.tools import sandbox as sbx


def _fake_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, issuer_uid: int = 462, root_uid: int = 0) -> tuple[Path, Path]:
    root = tmp_path / "task-authority"
    root.mkdir()
    private = root / "private"
    private.mkdir(mode=0o700)
    (private / "secret.pem").write_text("never inspect")
    trust = root / "trust.json"
    trust.write_text(json.dumps({"schema": "lfl.task-authority-trust/v1", "issuer_uid": issuer_uid}))
    (root / "leases").mkdir()
    real_lstat = os.lstat
    real_open = os.open
    real_fstat = os.fstat
    real_access = os.access
    real_scandir = os.scandir
    trust_fds: set[int] = set()

    def fake_uid(st: os.stat_result, uid: int) -> os.stat_result:
        row = list(st)
        row[4] = uid
        return os.stat_result(row)

    def fake_lstat(path: os.PathLike[str] | str, *args: object, **kwargs: object) -> os.stat_result:
        st = real_lstat(path, *args, **kwargs)
        if os.fspath(path) == str(root):
            return fake_uid(st, root_uid)
        if os.fspath(path) == str(private):
            return fake_uid(st, 462)
        return st

    def fake_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == str(trust):
            trust_fds.add(fd)
        return fd

    def fake_fstat(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        return fake_uid(st, 0) if fd in trust_fds else st

    def fake_access(path: os.PathLike[str] | str, mode: int, *args: object, **kwargs: object) -> bool:
        if os.fspath(path) == str(private):
            return False
        return real_access(path, mode, *args, **kwargs)

    def fake_scandir(path: os.PathLike[str] | str) -> object:
        if os.fspath(path) == str(private):
            raise PermissionError(13, "Host issuer private subtree is inaccessible", str(private))
        return real_scandir(path)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "access", fake_access)
    monkeypatch.setattr(os, "scandir", fake_scandir)
    return root, private


def test_root_owned_issuer_private_opaque_but_public_receipts_scanned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, _private = _fake_host(monkeypatch, tmp_path)
    assert sbx._prepare_protected_roots([str(root)]) == [str(root)]
    public = root / "leases" / "lease.json"
    public.write_text("public receipt")
    os.link(public, tmp_path / "alias.json")
    with pytest.raises(RuntimeError, match="hardlink alias"):
        sbx._prepare_protected_roots([str(root)])


def test_untrusted_issuer_uid_still_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, _private = _fake_host(monkeypatch, tmp_path, issuer_uid=999)
    with pytest.raises(RuntimeError, match="cannot be inspected"):
        sbx._prepare_protected_roots([str(root)])


def test_untrusted_authority_root_still_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, _private = _fake_host(monkeypatch, tmp_path, root_uid=os.geteuid() or 1001)
    with pytest.raises(RuntimeError, match="cannot be inspected"):
        sbx._prepare_protected_roots([str(root)])


def test_real_mac_host_private_directory_stays_inaccessible() -> None:
    root = Path("/Library/LFL-TaskHostIssuer/task-authority")
    if sys.platform != "darwin" or not (root / "trust.json").is_file():
        pytest.skip("No independently installed Mac Host issuer")
    assert not os.access(root / "private", os.R_OK | os.X_OK)
    assert sbx._prepare_protected_roots([str(root)]) == [str(root)]
    assert stat.S_IMODE((root / "private").lstat().st_mode) == 0o700


def test_external_audit_symlink_file_target_is_idempotent_and_exactly_denied(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    external = tmp_path / "providers.json"
    external.write_text("{}")
    (audit / "providers.json").symlink_to(external)
    protected = sbx._prepare_protected_roots([str(audit)])
    assert str(external) in protected
    assert sbx._prepare_protected_roots(protected) == protected
    profile = sbx.sandbox_exec_profile([str(tmp_path)], protected_roots=protected)
    assert f'(deny file-write* (literal "{external}"))' in profile
    assert f'(deny file-write* (subpath "{audit}"))' in profile
