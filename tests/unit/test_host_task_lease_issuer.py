"""Offline separated-UID Task Lease issuer: cross-library signatures and denial."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from llm_loop.core.task_capabilities import CapabilityRequest
from llm_loop.tools.task_authority import TaskAuthorityError, verify_signed_task_lease
from scripts import host_task_lease_issuer as issuer

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)


def test_mac_task_host_anchor_is_dedicated_and_matches_runtime():
    from llm_loop.tools.task_runtime import _MAC_AUTHORITY

    assert issuer._BASE == _MAC_AUTHORITY
    assert issuer._BASE.parent == Path("/Library/LFL-TaskHostIssuer")
    assert issuer._BASE.parent / "runtime" / "site" == issuer._TRUSTED_SITE
    assert "Application Support" not in str(issuer._BASE)


def test_crypto_import_denies_group_writable_dedicated_ancestor(monkeypatch):
    def fake_lstat(path):
        mode = 0o775 if str(path) == "/Library/LFL-TaskHostIssuer" else 0o755
        return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=0, st_gid=80)

    with monkeypatch.context() as m:
        m.setattr(Path, "lstat", fake_lstat)
        with pytest.raises(issuer.IssuerHoldError, match="issuer_crypto_runtime_untrusted"):
            issuer._crypto()


@pytest.mark.parametrize(
    ("path", "mode", "uid", "gid", "platform", "allowed"),
    [
        ("/Library", 0o775, 0, 80, "darwin", True),
        ("/Library", 0o755, 0, 0, "darwin", True),
        ("/Library", 0o775, 0, 80, "linux", False),
        ("/Library", 0o775, 0, 20, "darwin", False),
        ("/Library", 0o773, 0, 80, "darwin", False),
        ("/Library", 0o777, 0, 80, "darwin", False),
        ("/Library", 0o775, 501, 80, "darwin", False),
        ("/Library/LFL-TaskHostIssuer", 0o775, 0, 80, "darwin", False),
        ("/", 0o755, 0, 0, "darwin", True),
    ],
)
def test_root_ancestor_exception_is_exact_mac_admin_library(
    monkeypatch, path, mode, uid, gid, platform, allowed
):
    import llm_loop.tools.task_authority as authority

    info = SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid, st_gid=gid)
    with monkeypatch.context() as m:
        m.setattr(issuer.sys, "platform", platform)
        assert issuer._trusted_root_ancestor(Path(path), info) is allowed
        assert authority._trusted_root_ancestor(Path(path), info) is allowed


def test_issuer_create_and_revoke_sync_parent_directory(tmp_path, monkeypatch):
    """No SIGNED/REVOKED acknowledgement before the directory entry is durable."""
    actual_fsync = os.fsync
    synced: list[str] = []

    def recorded_fsync(fd):
        synced.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        actual_fsync(fd)

    with monkeypatch.context() as m:
        m.setattr(issuer.os, "fsync", recorded_fsync)
        target = tmp_path / "lease.json"
        issuer._create(target, b"active", 0o600)
        assert synced == ["file", "dir"]
        temp = tmp_path / "revoked.tmp"
        issuer._create(temp, b"revoked", 0o600)
        synced.clear()
        issuer._replace_state_durable(temp, target)
        assert synced == ["dir"]
        assert target.read_bytes() == b"revoked"


def test_public_receipt_mode_survives_restrictive_host_umask(tmp_path):
    original = os.umask(0o077)
    try:
        public = tmp_path / "signed-public.json"
        private = tmp_path / "private-approval.json"
        issuer._create(public, b"public", 0o644)
        issuer._create(private, b"private", 0o600)
    finally:
        os.umask(original)
    assert stat.S_IMODE(public.stat().st_mode) == 0o644
    assert stat.S_IMODE(private.stat().st_mode) == 0o600


def test_session_binding_directory_public_despite_umask(tmp_path, monkeypatch):
    monkeypatch.setattr(issuer, "_ISSUER_UID", os.getuid())
    original = os.umask(0o077)
    try:
        directory = tmp_path / "session-hash"
        directory.mkdir(mode=0o755)
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        issuer._publish_binding_directory(directory)
    finally:
        os.umask(original)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755
    directory.chmod(0o700)
    issuer._publish_binding_directory(directory)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o755


def test_session_binding_directory_rejects_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(issuer, "_ISSUER_UID", os.getuid())
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "session-hash"
    link.symlink_to(target, target_is_directory=True)
    before = stat.S_IMODE(target.stat().st_mode)
    with pytest.raises(OSError):
        issuer._publish_binding_directory(link)
    assert stat.S_IMODE(target.stat().st_mode) == before


def test_revoke_parent_sync_failure_never_reports_success(tmp_path, monkeypatch):
    target, temporary = tmp_path / "lease.json", tmp_path / "revoke.tmp"
    target.write_bytes(b"active")
    temporary.write_bytes(b"revoked")

    def failed_sync(_path):
        raise OSError("directory fsync failed")

    monkeypatch.setattr(issuer, "_sync_parent_directory", failed_sync)
    with pytest.raises(OSError, match="directory fsync failed"):
        issuer._replace_state_durable(temporary, target)


@pytest.fixture
def approval(tmp_path):
    a, b = tmp_path / "project-a", tmp_path / "project-b"
    a.mkdir()
    b.mkdir()
    return {
        "schema": "lfl.task-approval/v1",
        "approval_id": "approval-12345678",
        "approved_at": NOW.isoformat(),
        "approved_by": "operator",
        "purpose": "one bounded two-project task",
        "goal_id": "GOAL-test",
        "task_id": "TASK-test",
        "owner_session_id": "owner-session",
        "agent_id": "agent-1",
        "lane_id": "lane-1",
        "revision": 1,
        "authority_epoch": 3,
        "ttl_seconds": 3600,
        "parent_lease_id": None,
        "resources": [
            {"kind": "project", "identity": str(a), "verbs": ["read", "write"]},
            {"kind": "project", "identity": str(b), "verbs": ["read", "write", "git_commit"]},
        ],
    }


def _request(approval):
    return CapabilityRequest(
        approval["goal_id"],
        approval["task_id"],
        approval["owner_session_id"],
        approval["agent_id"],
        approval["lane_id"],
        approval["revision"],
        "project",
        approval["resources"][1]["identity"],
        "write",
    )


def test_separate_uid_issuer_cross_crypto_valid_and_revoke(approval):
    key = ECC.generate(curve="Ed25519")
    lease, state, lease_id = issuer.issue_receipts(
        approval,
        key,
        eddsa,
        now=NOW,
        lease_id="lease-12345678",
    )
    public = key.public_key().export_key(format="PEM").encode()
    req = _request(approval)
    claims = verify_signed_task_lease(public, lease, state, req, now=NOW)
    assert claims.lease_id == lease_id
    assert len(claims.resources) == 2
    revoked, ident = issuer.revoked_state(lease, key, eddsa)
    assert ident == lease_id
    with pytest.raises(TaskAuthorityError, match="authority_lease_revoked"):
        verify_signed_task_lease(public, lease, revoked, req, now=NOW)


def test_invalid_approval_scope_ttl_and_staleness_rejected(approval):
    key = ECC.generate(curve="Ed25519")
    variants = [
        {**approval, "ttl_seconds": 86401},
        {**approval, "approved_at": (NOW - timedelta(minutes=11)).isoformat()},
        {**approval, "resources": [{"kind": "project", "identity": "/", "verbs": ["write"]}]},
        {**approval, "resources": [{"kind": "service", "identity": "*", "verbs": ["restart"]}]},
        {**approval, "allow_all_shell": True},
        {**approval, "revision": True},
        {**approval, "parent_lease_id": "lease-parent123"},
    ]
    for invalid in variants:
        with pytest.raises(issuer.IssuerHoldError):
            issuer.issue_receipts(invalid, key, eddsa, now=NOW)


def test_wrong_key_cannot_revoke_lease(approval):
    key = ECC.generate(curve="Ed25519")
    lease, _state, _ = issuer.issue_receipts(approval, key, eddsa, now=NOW)
    with pytest.raises(issuer.IssuerHoldError, match="lease_receipt_signature_invalid"):
        issuer.revoked_state(lease, ECC.generate(curve="Ed25519"), eddsa)


def test_tampered_signed_lease_rejected_by_runtime(approval):
    key = ECC.generate(curve="Ed25519")
    lease, state, _ = issuer.issue_receipts(approval, key, eddsa, now=NOW)
    forged = json.loads(lease)
    forged["payload"]["resources"][0]["verbs"].append("delete")
    public = key.public_key().export_key(format="PEM").encode()
    with pytest.raises(TaskAuthorityError, match="authority_signature_invalid"):
        verify_signed_task_lease(
            public,
            json.dumps(forged).encode(),
            state,
            _request(approval),
            now=NOW,
        )


def test_unprivileged_cli_fails_closed_without_side_effects(capsys):
    code = issuer.main(["--mode", "keygen"])
    result = json.loads(capsys.readouterr().out)
    assert code == 1
    assert result["decision"] == "HOLD"
    assert result["reason"] == "issuer_uid_invalid"


@pytest.fixture
def lane_request_fixture(tmp_path):
    from llm_loop.introspection.goal import GoalStore
    from llm_loop.introspection.lane import LaneStore
    from llm_loop.introspection.task_store import TaskStore

    repo = (tmp_path / "repo").resolve()
    repo.mkdir()

    def git(path, *args):
        return subprocess.run(
            ["/usr/bin/git", "-C", str(path), *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    git(repo, "init", "-q", "-b", "main")
    (repo / "source.txt").write_text("initial")
    git(repo, "add", "source.txt")
    git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "initial")
    worktree = repo / ".worktrees" / "ordinary"
    git(repo, "worktree", "add", "-qb", "fix/ordinary", str(worktree))
    head = git(worktree, "rev-parse", "HEAD")
    audit = repo / "data" / "audit"
    session = "owner-session"
    goal = GoalStore(audit).create("ordinary task", session_id=session)
    tasks = TaskStore(audit)
    task = tasks.create(goal.id, "edit", acceptance=["bounded edit"])
    tasks.update(goal.id, task.task_id, status="in_progress")
    lanes = LaneStore(audit, lock_strict=True, enforce_cross_goal=True, repo_root=repo)
    lane = lanes.create(
        branch="fix/ordinary", worktree=str(worktree), base_main_sha=head,
        goal_id=goal.id, owner_session_id=session, paths=["source.txt"],
    )
    row = lanes.update(lane.lane_id, expected_version=1, status="active", head_sha=head)
    args = dict(repo=str(repo), workspace=str(worktree), lane_id=lane.lane_id,
                task_id=task.task_id, session_id=session)
    return args, lanes, tasks, goal.id, row, git


def _draft(args):
    request = issuer.lane_request(**args, now=NOW)
    raw = issuer.canonical(request) + b"\n"
    return request, raw, hashlib.sha256(raw).hexdigest()


def test_lane_request_is_read_only_and_owner_approval_reuses_signed_schema(lane_request_fixture):
    args, _lanes, _tasks, _goal, row, git = lane_request_fixture
    request, raw, digest = _draft(args)
    assert request["snapshot"]["head_sha"] == row["head_sha"]
    assert request["snapshot"]["lane_version"] == row["version"]
    assert request["ttl_seconds"] == 14400
    assert "approved_at" not in request and "approved_by" not in request
    assert request["resources"] == [{"kind": "project", "identity": args["workspace"],
                                     "verbs": issuer._LANE_VERBS}]
    assert git(args["workspace"], "status", "--porcelain") == ""
    seen = []
    approval = issuer._owner_lane_approval(
        raw, digest, lambda r, d: seen.append((r, d)) or True, clock=lambda: NOW,
    )
    assert seen == [(request, digest)]
    assert approval["schema"] == "lfl.task-approval/v1"
    assert approval["owner_session_id"] == args["session_id"]
    assert approval["resources"] == request["resources"]
    key = ECC.generate(curve="Ed25519")
    lease, state, _ident = issuer.issue_receipts(approval, key, eddsa, now=NOW)
    public = key.public_key().export_key(format="PEM").encode()
    capability = CapabilityRequest(
        approval["goal_id"], approval["task_id"], approval["owner_session_id"],
        approval["agent_id"], approval["lane_id"], approval["revision"],
        "project", args["workspace"], "git_commit",
    )
    claims = verify_signed_task_lease(public, lease, state, capability, now=NOW)
    assert claims.owner_session_id == args["session_id"]
    assert claims.expires_at == NOW + timedelta(hours=4)


@pytest.mark.parametrize("change", ["digest", "resource", "approval", "expired", "declined"])
def test_lane_request_denies_tamper_expiry_or_no_owner(lane_request_fixture, change):
    args, *_ = lane_request_fixture
    request, raw, digest = _draft(args)
    clock = NOW
    def confirm(_r, _d):
        return change != "declined"

    if change == "digest":
        digest = "0" * 64
    elif change == "resource":
        request["resources"][0]["verbs"].append("git_push")
        raw = issuer.canonical(request) + b"\n"
        digest = hashlib.sha256(raw).hexdigest()
    elif change == "approval":
        request["approved_by"] = "fake"
        raw = issuer.canonical(request) + b"\n"
        digest = hashlib.sha256(raw).hexdigest()
    elif change == "expired":
        clock += timedelta(minutes=31)
    with pytest.raises(issuer.IssuerHoldError):
        issuer._owner_lane_approval(raw, digest, confirm, clock=lambda: clock)


@pytest.mark.parametrize("change", ["lane", "head", "task", "branch"])
def test_lane_request_rechecks_live_state_after_owner_confirmation(lane_request_fixture, change):
    args, lanes, tasks, goal, row, git = lane_request_fixture
    _request_doc, raw, digest = _draft(args)

    def confirm(_request, _digest):
        if change == "lane":
            lanes.update(args["lane_id"], expected_version=row["version"], head_sha=row["head_sha"])
        elif change == "head":
            git(args["workspace"], "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-qm", "external")
        elif change == "task":
            tasks.update(goal, args["task_id"], status="done")
        else:
            git(args["workspace"], "switch", "-qc", "fix/other")
        return True

    with pytest.raises(issuer.IssuerHoldError):
        issuer._owner_lane_approval(raw, digest, confirm, clock=lambda: NOW)


def test_lane_request_rejects_main_wrong_owner_and_overlong_ttl(lane_request_fixture):
    args, *_ = lane_request_fixture
    for changes in (
        {"workspace": args["repo"]}, {"session_id": "other-session"},
        {"ttl_seconds": issuer._LANE_MAX_TTL + 1},
    ):
        with pytest.raises(issuer.IssuerHoldError):
            issuer.lane_request(**{**args, **changes})


def test_lane_issue_requires_installed_host_before_reading_request(capsys):
    assert issuer.main(["--mode", "issue-lane", "--request-sha256", "0" * 64]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "issuer_uid_invalid"


def test_lane_issue_publishes_once_and_rejects_duplicate_session(
    lane_request_fixture, tmp_path, monkeypatch,
):
    args, *_ = lane_request_fixture
    base = tmp_path / "authority"
    for name in ("private/approvals", "private/consumed", "leases", "states", "bindings"):
        (base / name).mkdir(parents=True)
    monkeypatch.setattr(issuer, "_BASE", base)
    monkeypatch.setattr(issuer, "_ISSUER_UID", os.getuid())
    seen = []
    monkeypatch.setattr(issuer, "_owner_confirm", lambda r, d: seen.append(d) or True)
    request = issuer.lane_request(**args)
    raw = issuer.canonical(request) + b"\n"
    digest = hashlib.sha256(raw).hexdigest()
    key = ECC.generate(curve="Ed25519")
    result = issuer._issue_lane_request(raw, digest, key, eddsa)
    assert result["decision"] == "SIGNED"
    assert len(list((base / "private" / "approvals").glob("*.json"))) == 1
    assert len(list((base / "private" / "consumed").glob("*.used"))) == 1
    assert len(list((base / "bindings").glob("*/*.json"))) == 1
    second = issuer.canonical(issuer.lane_request(**args)) + b"\n"
    with pytest.raises(issuer.IssuerHoldError, match="issuer_session_already_authorized"):
        issuer._issue_lane_request(second, hashlib.sha256(second).hexdigest(), key, eddsa)
    assert seen == [digest]  # no second Owner prompt for an already active lease
    assert len(list((base / "leases").glob("*.json"))) == 1


def test_one_owner_approval_two_real_run_activations_and_revocation(
    lane_request_fixture, tmp_path, monkeypatch,
):
    from llm_loop.core.message import ToolResultStatus
    from llm_loop.core.run_context import (
        current_session_id,
        current_task_execution,
        current_workspace_root,
    )
    from llm_loop.tools import task_runtime
    from llm_loop.tools.builtin.task_git_commit import TaskGitCommitTool

    args, lanes, _tasks, _goal, row, git = lane_request_fixture
    worktree = Path(args["workspace"])
    data = Path(args["repo"]) / "data"
    (data / "audit" / "git-locks").mkdir()
    host = tmp_path / "test-authority"
    host.mkdir()
    (host / "trust.json").write_text("test-only anchor")
    (host / "bindings").mkdir()
    request = issuer.lane_request(**args)
    raw = issuer.canonical(request) + b"\n"
    approvals = []
    approval = issuer._owner_lane_approval(
        raw, hashlib.sha256(raw).hexdigest(),
        lambda _r, _d: approvals.append(True) or True,
    )
    key = ECC.generate(curve="Ed25519")
    lease, state, ident = issuer.issue_receipts(approval, key, eddsa)
    public = key.public_key().export_key(format="PEM").encode()
    capability = CapabilityRequest(
        approval["goal_id"], approval["task_id"], approval["owner_session_id"],
        approval["agent_id"], approval["lane_id"], approval["revision"],
        "project", str(worktree), "git_commit",
    )

    class TestAuthority:
        def __init__(self, root):
            self.root = root

        def discover_for_session(self, session_id):
            assert session_id == approval["owner_session_id"]
            return verify_signed_task_lease(public, lease, state, capability)

        def verify(self, lease_id, request):
            assert lease_id == ident
            return verify_signed_task_lease(public, lease, state, request)

    monkeypatch.setattr(task_runtime, "RootOwnedTaskAuthority", TestAuthority)
    sid = current_session_id.set(args["session_id"])
    ws = current_workspace_root.set(str(worktree))
    try:
        for i in range(2):
            ctx = task_runtime.resolve_task_execution_for_run(
                session_id=args["session_id"], workspace_root=str(worktree),
                data_dir=str(data), authority_root=host,
            )
            assert ctx is not None and ctx.lease_id == ident
            token = current_task_execution.set(ctx)
            try:
                (worktree / "source.txt").write_text(f"change {i}")
                result = TaskGitCommitTool().execute(paths=["source.txt"], message=f"feat: {i}")
                assert result.status == ToolResultStatus.SUCCESS, result.content
            finally:
                current_task_execution.reset(token)
        assert len(approvals) == 1
        assert lanes.get(args["lane_id"])["version"] == row["version"] + 2
        head = git(worktree, "rev-parse", "HEAD")
        ctx = task_runtime.resolve_task_execution_for_run(
            session_id=args["session_id"], workspace_root=str(worktree),
            data_dir=str(data), authority_root=host,
        )
        token = current_task_execution.set(ctx)
        try:
            state, _ = issuer.revoked_state(lease, key, eddsa)
            (worktree / "source.txt").write_text("must not commit")
            denied = TaskGitCommitTool().execute(paths=["source.txt"], message="feat: denied")
            assert denied.error_type == "authority_lease_revoked"
            assert git(worktree, "rev-parse", "HEAD") == head
            assert not git(worktree, "diff", "--cached", "--name-only")
        finally:
            current_task_execution.reset(token)
    finally:
        current_workspace_root.reset(ws)
        current_session_id.reset(sid)


def test_lane_gitconfig_bootstrap_create_once_and_preserve_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(issuer, "_ISSUER_UID", os.getuid())
    monkeypatch.setattr(issuer, "_trusted_root_ancestor", lambda path, st: stat.S_ISDIR(st.st_mode))
    gid = os.getgid()
    target = tmp_path / "gitconfig-safe-directories"
    assert issuer._initialize_lane_gitconfig(tmp_path, gid) == "INITIALIZED"
    assert target.read_bytes() == b""
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    target.write_text("[safe]\n\tdirectory = /test/worktree\n")
    before = target.stat()
    assert issuer._initialize_lane_gitconfig(tmp_path, gid) == "ALREADY_INITIALIZED"
    assert target.read_text() == "[safe]\n\tdirectory = /test/worktree\n"
    assert target.stat().st_ino == before.st_ino
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    target.chmod(0o666)
    with pytest.raises(issuer.IssuerHoldError, match="issuer_lane_gitconfig_untrusted"):
        issuer._initialize_lane_gitconfig(tmp_path, gid)
    assert stat.S_IMODE(target.stat().st_mode) == 0o666


def test_lane_gitconfig_bootstrap_denies_links_without_modifying_target(tmp_path, monkeypatch):
    monkeypatch.setattr(issuer, "_ISSUER_UID", os.getuid())
    monkeypatch.setattr(issuer, "_trusted_root_ancestor", lambda path, st: stat.S_ISDIR(st.st_mode))
    other = tmp_path / "untouched"
    other.write_text("unchanged")
    other.chmod(0o644)
    target = tmp_path / "gitconfig-safe-directories"
    target.symlink_to(other)
    with pytest.raises(OSError):
        issuer._initialize_lane_gitconfig(tmp_path, os.getgid())
    target.unlink()
    os.link(other, target)
    with pytest.raises(issuer.IssuerHoldError, match="issuer_lane_gitconfig_untrusted"):
        issuer._initialize_lane_gitconfig(tmp_path, os.getgid())
    assert other.read_text() == "unchanged"


def test_lane_gitconfig_bootstrap_nonroot_and_extra_args_denied(monkeypatch, capsys):
    monkeypatch.setattr(issuer.os, "getuid", lambda: 501)
    monkeypatch.setattr(issuer.os, "geteuid", lambda: 501)
    monkeypatch.setattr(issuer, "_crypto", lambda: pytest.fail("bootstrap must not load signing keys"))
    assert issuer.main(["--mode", "init-lane-gitconfig"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "issuer_uid_invalid"
    assert issuer.main(["--mode", "init-lane-gitconfig", "--workspace", "/tmp"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "issuer_bootstrap_arguments_invalid"


def test_lane_gitconfig_bootstrap_dispatch_never_loads_crypto(tmp_path, monkeypatch, capsys):
    import pwd

    monkeypatch.setattr(issuer, "_BASE", tmp_path)
    checks = []
    monkeypatch.setattr(issuer, "_check_installed", lambda **kwargs: checks.append(kwargs))
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_name="_lfl_dual_witness", pw_gid=20))
    monkeypatch.setattr(issuer, "_initialize_lane_gitconfig", lambda directory, gid: "ALREADY_INITIALIZED" if directory == tmp_path and gid == 20 else pytest.fail("wrong bootstrap target"))
    monkeypatch.setattr(issuer, "_crypto", lambda: pytest.fail("bootstrap must not load signing keys"))
    assert issuer.main(["--mode", "init-lane-gitconfig"]) == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "ALREADY_INITIALIZED"}
    assert checks == [{"bootstrap": True}]
