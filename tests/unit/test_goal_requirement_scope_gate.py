"""Pinned REQ scope is owner-bound, immutable, and fail-closed at complete."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_evidence import TaskEvidenceVerifier
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_goal import run_checkpoint_goal, run_update_goal

ACCEPTANCE = "设计需求已实现且真实证据可核验"


class _Verifier:
    status = "verified"

    def verify(self, refs):
        assert refs
        return SimpleNamespace(
            status=self.status,
            checked_at="2026-11-20T00:00:00+00:00",
            refs_digest="fixture",
        )


@pytest.fixture(autouse=True)
def _owner():
    token = current_session_id.set("s-req-owner")
    yield
    current_session_id.reset(token)


def _fixture(tmp_path: Path, *, task_done: bool = True):
    repo = tmp_path / "repo"
    audit = repo / "data" / "audit"
    audit.mkdir(parents=True)
    verifier = _Verifier()
    host = SimpleNamespace(
        audit_dir=str(audit),
        session_id="s-req-owner",
        ctx=SimpleNamespace(task_evidence_verifier=verifier),
    )
    goal = GoalStore(audit).create("REQ专项Goal", session_id="s-req-owner")
    store = TaskStore(audit, evidence_verifier=cast(TaskEvidenceVerifier, verifier))
    task = store.create(
        goal.id, "REQ-001", acceptance=[ACCEPTANCE], evidence_required=True
    )
    if task_done:
        store.update(goal.id, task.task_id, status="in_progress")
        store.update(
            goal.id, task.task_id, status="done",
            evidence_refs=["evidence://v1/real-fixture"],
        )
    design = repo / "docs" / "design" / "approved.md"
    design.parent.mkdir(parents=True)
    design.write_text(
        f"<!-- LFL-REQ-GOAL: {goal.id} -->\n"
        "<!-- LFL-REQ-MATRIX:v1 -->\n"
        "| REQ | Task | Slice | Required | Acceptance | Incremental | Final | Scope approval |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| REQ-001 | {task.task_id} | A | yes | {ACCEPTANCE} | tests/unit/test_req.py | R9,CI | - |\n"
        "<!-- /LFL-REQ-MATRIX -->\n",
        encoding="utf-8",
    )
    scope = {
        "design_path": "docs/design/approved.md",
        "design_sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
    }
    return host, goal.id, task.task_id, design, scope, verifier


def _bind(host, gid: str, scope: dict, *, version: int | None = 1):
    return run_checkpoint_goal(
        None,
        host,
        {
            "goal_id": gid,
            "what": "Owner批准并冻结REQ矩阵",
            "expected_version": version,
            "requirements_scope": scope,
        },
    )


def _complete(host, gid: str, *, refs=None):
    args = {"goal_id": gid, "status": "complete"}
    if refs is not None:
        args["evidence_refs"] = refs
    return run_update_goal(None, host, args)


def _record(host, gid: str) -> dict:
    record = GoalStore(host.audit_dir).get(gid)
    assert record is not None
    return record


def test_owner_cas_scope_binding_and_verified_complete(tmp_path):
    host, gid, _, _, scope, _ = _fixture(tmp_path)
    result = _bind(host, gid, scope)
    assert result.status == ToolResultStatus.SUCCESS
    record = _record(host, gid)
    assert record["requirements_scope"] == scope
    assert record["version"] == 2
    assert _complete(host, gid).status == ToolResultStatus.SUCCESS


def test_scope_is_immutable_and_cas_protected(tmp_path):
    host, gid, _, _, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, scope, version=9).status == ToolResultStatus.FAILURE
    assert not _record(host, gid).get("requirements_scope")
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    assert _bind(host, gid, scope, version=2).status == ToolResultStatus.FAILURE
    assert _record(host, gid)["requirements_scope"] == scope


def test_missing_cas_and_wrong_owner_rejected(tmp_path):
    host, gid, _, _, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, scope, version=None).status == ToolResultStatus.FAILURE
    token = current_session_id.set("other-session")
    try:
        assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
    finally:
        current_session_id.reset(token)
    assert not _record(host, gid).get("requirements_scope")


@pytest.mark.parametrize("bad_path", ["../../etc/passwd", "/tmp/approved.md", "docs/design/../other.md"])
def test_scope_external_path_rejected(tmp_path, bad_path):
    host, gid, _, _, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, {**scope, "design_path": bad_path}).status == ToolResultStatus.FAILURE


def test_scope_symlink_outside_design_rejected(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    link = design.parent / "escape.md"
    link.symlink_to(tmp_path / "outside.md")
    assert _bind(host, gid, {**scope, "design_path": "docs/design/escape.md"}).status == ToolResultStatus.FAILURE


def test_wrong_sha_or_goal_marker_cannot_bind(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, {**scope, "design_sha256": "a" * 64}).status == ToolResultStatus.FAILURE
    design.write_text(design.read_text().replace(gid, "GOAL-other"))
    scope["design_sha256"] = hashlib.sha256(design.read_bytes()).hexdigest()
    assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE


def test_tampered_design_after_binding_blocks_complete(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    design.write_text(design.read_text() + "\nnew unapproved REQ\n")
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "requirement_coverage_unverified" in result.content
    assert _record(host, gid)["status"] == "active"


def test_deleted_pinned_design_blocks_complete(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    design.unlink()
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "requirement_coverage_unverified" in result.content
    assert "coverage_unavailable" in result.content


def test_stale_evidence_blocks_even_if_taskstore_says_verified(tmp_path):
    host, gid, _, _, scope, verifier = _fixture(tmp_path)
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    verifier.status = "blob_missing"
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "evidence_stale" in result.content


def test_missing_verifier_blocks_scoped_complete(tmp_path):
    host, gid, _, _, scope, _ = _fixture(tmp_path)
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    host.ctx.task_evidence_verifier = None
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "requirement_scope_unavailable" in result.content


def test_unmapped_done_task_blocks_complete(tmp_path):
    host, gid, _, _, scope, verifier = _fixture(tmp_path)
    store = TaskStore(host.audit_dir, evidence_verifier=cast(TaskEvidenceVerifier, verifier))
    extra = store.create(gid, "Unmapped", acceptance=["extra"], evidence_required=True)
    store.update(gid, extra.task_id, status="in_progress")
    store.update(gid, extra.task_id, status="done", evidence_refs=["evidence://v1/extra"])
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    result = _complete(host, gid)
    assert result.status == ToolResultStatus.BLOCKED
    assert "unmapped_task" in result.content


def test_cancelled_required_task_cannot_be_waived_by_self_report(tmp_path):
    host, gid, tid, _, scope, _ = _fixture(tmp_path, task_done=False)
    TaskStore(host.audit_dir).update(gid, tid, status="cancelled")
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    result = _complete(host, gid, refs=["evidence://v1/owner-self-report"])
    assert result.status == ToolResultStatus.BLOCKED
    assert "required_not_done" in result.content


def test_unbound_legacy_goal_unchanged(tmp_path):
    host, gid, _, _, _, _ = _fixture(tmp_path)
    assert _complete(host, gid).status == ToolResultStatus.SUCCESS


def _managed_release(host, design: Path) -> tuple[Path, Path, Path]:
    """Model a verified source release without copying the design into shared root."""
    repo = Path(host.audit_dir).parents[1]
    sha = "a" * 40
    release = repo / ".releases" / sha
    pinned = release / "docs" / "design" / "approved.md"
    pinned.parent.mkdir(parents=True)
    pinned.write_bytes(design.read_bytes())
    manifest = repo / "data" / "runtime" / "managed_service_deployment.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {"code_root": str(release), "runtime_root": str(repo), "git_head": sha}
        ),
        encoding="utf-8",
    )
    return pinned, manifest, release


def test_managed_release_scope_binds_without_shared_root_design(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    pinned, _, _ = _managed_release(host, design)
    design.unlink()
    assert pinned.is_file() and not design.exists()
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    assert _complete(host, gid).status == ToolResultStatus.SUCCESS


def test_managed_release_prefers_pinned_source_over_root_decoy(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    pinned, _, _ = _managed_release(host, design)
    design.write_text("untrusted old root copy", encoding="utf-8")
    assert _bind(host, gid, scope).status == ToolResultStatus.SUCCESS
    pinned.write_text(pinned.read_text() + "\nmodified", encoding="utf-8")
    assert _complete(host, gid).status == ToolResultStatus.BLOCKED
    assert _record(host, gid)["status"] == "active"


def test_managed_release_rejects_stale_or_cross_workspace_pointer(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    _, manifest, release = _managed_release(host, design)
    for bad in (
        {"code_root": str(release.parent / ("b" * 40))},
        {"runtime_root": str(tmp_path / "foreign")},
        {"git_head": "not-a-commit"},
    ):
        state = json.loads(manifest.read_text())
        state.update(bad)
        manifest.write_text(json.dumps(state))
        assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
        assert not _record(host, gid).get("requirements_scope")
        manifest.write_text(
            json.dumps(
                {"code_root": str(release), "runtime_root": str(Path(host.audit_dir).parents[1]), "git_head": "a" * 40}
            )
        )


def test_managed_release_rejects_symlink_escape(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    _, _, release = _managed_release(host, design)
    outside = tmp_path / "outside"
    shutil.move(str(release), str(outside))
    release.symlink_to(outside, target_is_directory=True)
    assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
    assert not _record(host, gid).get("requirements_scope")


def test_managed_release_missing_or_corrupt_state_does_not_fallback(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    _, manifest, _ = _managed_release(host, design)
    manifest.unlink()
    assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
    manifest.write_text("{corrupt", encoding="utf-8")
    assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
    assert not _record(host, gid).get("requirements_scope")


def test_managed_release_rejects_symlinked_identity(tmp_path):
    host, gid, _, design, scope, _ = _fixture(tmp_path)
    _, manifest, _ = _managed_release(host, design)
    other = tmp_path / "outside-identity.json"
    other.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(other)
    assert _bind(host, gid, scope).status == ToolResultStatus.FAILURE
    assert not _record(host, gid).get("requirements_scope")
