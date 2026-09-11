from __future__ import annotations

from pathlib import Path

from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.workspace.artifacts import WorkspaceArtifactStore
from llm_loop.workspace.file_service import FileService


def test_capable_edit_schema_requires_version_ref_while_bare_legacy_stays_optional(
    tmp_path: Path,
) -> None:
    """Only the formally assembled shared-file capability gets the hard precondition."""
    store = WorkspaceArtifactStore(tmp_path / "artifacts")
    service = FileService(artifact_store=store, lock_root=tmp_path / "locks")
    strict = EditFileTool(
        artifact_store=store,
        file_service=service,
        require_version_precondition=True,
    )
    legacy = EditFileTool(artifact_store=store, file_service=service)

    assert "expected_snapshot_ref" in strict.parameters["required"]
    assert "expected_snapshot_ref" not in legacy.parameters["required"]

    strict_path = tmp_path / "strict.txt"
    strict_path.write_text("old\n", encoding="utf-8")
    rejected = strict.execute(path=str(strict_path), old_string="old", new_string="new")
    assert rejected.status.value == "error"
    assert rejected.error_type == "VersionPreconditionRequired"
    assert strict_path.read_text(encoding="utf-8") == "old\n"

    legacy_path = tmp_path / "legacy-direct.txt"
    legacy_path.write_text("old\n", encoding="utf-8")
    result = legacy.execute(path=str(legacy_path), old_string="old", new_string="new")
    assert result.status.value == "success"
    assert legacy_path.read_text(encoding="utf-8") == "new\n"


def test_strict_edit_schema_cannot_be_assembled_without_snapshot_capability() -> None:
    try:
        EditFileTool(require_version_precondition=True)
    except ValueError as exc:
        assert "artifact_store" in str(exc)
    else:
        raise AssertionError("strict edit_file assembled without artifact_store")
