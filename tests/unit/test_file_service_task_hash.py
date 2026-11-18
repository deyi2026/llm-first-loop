"""FileService exact-byte SHA precondition for trusted cross-project edits."""

from __future__ import annotations

import hashlib
import os

import pytest

from llm_loop.workspace.file_service import FileService, FileServiceError


def test_expected_sha256_is_checked_inside_path_lock(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "data.txt"
    path.write_text("old value\n")
    service = FileService(lock_root=tmp_path / "locks")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = service.edit(
        path=path,
        old_string="old",
        new_string="new",
        expected_sha256=before,
        workspace_scope=str(root),
    )
    assert result.applied
    assert path.read_text() == "new value\n"
    with pytest.raises(FileServiceError, match="VersionConflict"):
        service.edit(
            path=path,
            old_string="new",
            new_string="bad",
            expected_sha256=before,
            workspace_scope=str(root),
        )
    assert path.read_text() == "new value\n"


def test_same_size_mtime_replacement_cannot_replay_old_hash(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "data.txt"
    path.write_bytes(b"alpha")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    stat_before = path.stat()
    path.write_bytes(b"bravo")
    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    service = FileService(lock_root=tmp_path / "locks")
    with pytest.raises(FileServiceError, match="VersionConflict"):
        service.edit(
            path=path,
            old_string="bravo",
            new_string="other",
            expected_sha256=before,
            workspace_scope=str(root),
        )
    assert path.read_bytes() == b"bravo"


def test_invalid_hash_refused_before_write(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "data.txt"
    path.write_text("unchanged")
    service = FileService(lock_root=tmp_path / "locks")
    with pytest.raises(FileServiceError, match="VersionPreconditionInvalid"):
        service.edit(
            path=path,
            old_string="unchanged",
            new_string="modified",
            expected_sha256="not-a-hash",
            workspace_scope=str(root),
        )
    assert path.read_text() == "unchanged"
