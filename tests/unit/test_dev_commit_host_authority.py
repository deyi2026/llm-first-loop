"""Real Ed25519 one-use Host grant tests, with disposable local identities."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dev_commit_host_authority as host

GRANT = "dev-commit-test-0123456789abcdef"
GOAL = "GOAL-20261120-022593f7"
REQ = "REQ-FLOW-004"
BASE = "a" * 40
HEAD = "b" * 40
TREE = "c" * 40


@pytest.fixture
def keys(monkeypatch):
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    monkeypatch.setattr(host, "_crypto", lambda: (ECC, eddsa))
    key = ECC.generate(curve="Ed25519")
    return key.export_key(format="PEM").encode(), key.public_key().export_key(format="PEM").encode()


@pytest.fixture
def store(tmp_path: Path):
    ledger = tmp_path / "dev-commit-ledger.jsonl"
    ledger.write_bytes(b"")
    ledger.chmod(0o600)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    return ledger, receipts


def _context() -> dict:
    return {
        "repo": host.REPO, "worktree": "/test/worktree", "branch": "feat/test",
        "head": HEAD, "tree": TREE, "base": BASE, "goal": GOAL, "req": REQ,
        "lane_id": "lane-123", "lane_version": 1, "message_sha256": "d" * 64,
        "paths": ["src/llm_loop/pkg/feature.py"],
    }


def _approval(ctx: dict, now: float) -> dict:
    return {
        "schema": "lfl.dev_commit.approval.v1", "approval_id": GRANT,
        "context": ctx, "expires_at": now + 240,
    }


def _receipt(ctx: dict, now: float) -> dict:
    return {
        "schema": "lfl.dev_gate.v1", "status": "PASS",
        "release_qualified": False, "goal_id": ctx["goal"],
        "req_id": ctx["req"], "base": ctx["base"], "head": ctx["head"],
        "staged_tree": ctx["tree"], "input_fingerprint": "e" * 64,
        "selected_tests": ["tests/unit/test_feature.py"],
        "checks": [
            {"exit_code": 0, "argv": ["-m", "ruff", "check"]},
            {"exit_code": 0, "argv": ["-m", "pyright"]},
            {"exit_code": 0, "argv": ["-m", "pytest", "-q"]},
        ],
        "completed_at": now - 1, "blockers": [],
    }


def _issue(keys, store, ctx, now):
    private, _ = keys
    ledger, receipts = store
    result = host.issue_grant(
        approval=_approval(ctx, now), context=ctx, private_pem=private,
        ledger=ledger, receipts=receipts, now=now, ledger_owner=os.geteuid(),
    )
    envelope = json.loads((receipts / f"{GRANT}.json").read_text())
    return result, envelope


def _consume(keys, store, ctx, receipt, envelope, now):
    _, public = keys
    ledger, _ = store
    return host.consume_grant(
        grant_id=GRANT, context=ctx, receipt=receipt, envelope=envelope,
        public_pem=public, ledger=ledger, now=now, ledger_owner=os.geteuid(),
    )


def test_real_ed25519_issue_consume_once(keys, store):
    now = time.time()
    ctx = _context()
    issued, envelope = _issue(keys, store, ctx, now)
    assert issued["decision"] == "SIGNED"
    result = _consume(keys, store, ctx, _receipt(ctx, now), envelope, now)
    assert result == {
        "decision": "CONSUMED", "grant_id": GRANT, "tree": TREE,
        "release_qualified": False,
    }
    with pytest.raises(host.HostHoldError, match="dev_grant_replayed"):
        _consume(keys, store, ctx, _receipt(ctx, now), envelope, now)
    with pytest.raises(host.HostHoldError, match="dev_approval_already_used"):
        _issue(keys, store, ctx, now)


@pytest.mark.parametrize("field", [
    "tree", "head", "base", "goal", "req", "branch", "lane_id",
    "lane_version", "message_sha256", "worktree",
])
def test_any_signed_context_change_denied(keys, store, field):
    now = time.time()
    ctx = _context()
    _, envelope = _issue(keys, store, ctx, now)
    changed = dict(ctx)
    changed[field] = "modified"
    with pytest.raises(host.HostHoldError, match="dev_grant_context_or_expiry_invalid"):
        _consume(keys, store, changed, _receipt(changed, now), envelope, now)


@pytest.mark.parametrize("field,value", [
    ("status", "DRY_RUN"),
    ("release_qualified", True),
    ("staged_tree", "0" * 40),
    ("input_fingerprint", "invalid"),
    ("selected_tests", []),
    ("checks", [{"exit_code": 1}]),
    ("checks", [{"exit_code": 0, "argv": ["-m", "pytest", "-q"]}]),
    ("completed_at", 0),
])
def test_untrusted_dev_receipt_denied(keys, store, field, value):
    now = time.time()
    ctx = _context()
    _, envelope = _issue(keys, store, ctx, now)
    receipt = _receipt(ctx, now)
    receipt[field] = value
    with pytest.raises(host.HostHoldError, match="dev_test_receipt_invalid"):
        _consume(keys, store, ctx, receipt, envelope, now)


def test_signature_tamper_and_wrong_public_key_denied(keys, store, monkeypatch):
    from Crypto.PublicKey import ECC

    now = time.time()
    ctx = _context()
    _, envelope = _issue(keys, store, ctx, now)
    tampered = json.loads(json.dumps(envelope))
    tampered["payload"]["context"]["tree"] = "0" * 40
    with pytest.raises(host.HostHoldError, match="dev_grant_signature_invalid"):
        _consume(keys, store, ctx, _receipt(ctx, now), tampered, now)
    wrong = ECC.generate(curve="Ed25519").public_key().export_key(format="PEM").encode()
    with pytest.raises(host.HostHoldError, match="dev_key_id_mismatch"):
        host.consume_grant(
            grant_id=GRANT, context=ctx, receipt=_receipt(ctx, now),
            envelope=envelope, public_pem=wrong, ledger=store[0],
            now=now, ledger_owner=os.geteuid(),
        )


def test_expiry_and_missing_ledger_fail_closed(keys, store):
    now = time.time()
    ctx = _context()
    _, envelope = _issue(keys, store, ctx, now)
    with pytest.raises(host.HostHoldError, match="dev_grant_context_or_expiry_invalid"):
        _consume(keys, store, ctx, _receipt(ctx, now + 301), envelope, now + 301)
    store[0].unlink()
    with pytest.raises(FileNotFoundError):
        _consume(keys, store, ctx, _receipt(ctx, now), envelope, now)


def test_root_approval_must_match_exact_context_and_freshness(keys, store):
    now = time.time()
    ctx = _context()
    bad = _approval(ctx, now)
    bad["context"] = {**ctx, "tree": "0" * 40}
    with pytest.raises(host.HostHoldError, match="owner_approval_invalid_or_stale"):
        host.issue_grant(
            approval=bad, context=ctx, private_pem=keys[0],
            ledger=store[0], receipts=store[1], now=now,
            ledger_owner=os.geteuid(),
        )
    bad = _approval(ctx, now)
    bad["expires_at"] = now + 900
    with pytest.raises(host.HostHoldError, match="owner_approval_invalid_or_stale"):
        host.issue_grant(
            approval=bad, context=ctx, private_pem=keys[0],
            ledger=store[0], receipts=store[1], now=now,
            ledger_owner=os.geteuid(),
        )
    assert store[0].read_bytes() == b""


def test_ledger_truncation_and_mode_refused(keys, store):
    now = time.time()
    ctx = _context()
    store[0].write_bytes(b'{"event":"issued"')
    with pytest.raises(host.HostHoldError, match="dev_ledger_truncated"):
        _issue(keys, store, ctx, now)
    store[0].write_bytes(b"")
    store[0].chmod(0o644)
    with pytest.raises(host.HostHoldError, match="dev_ledger_untrusted"):
        _issue(keys, store, ctx, now)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def live_repo(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat/host-test")
    _git(root, "config", "user.email", "host@example.invalid")
    _git(root, "config", "user.name", "Host Test")
    _git(root, "remote", "add", "origin", f"https://github.com/{host.REPO}.git")
    (root / ".gitignore").write_text("data/audit/\n")
    source = root / "src" / "llm_loop" / "pkg" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", base)
    source.write_text("x = 2\n")
    _git(root, "add", "src/llm_loop/pkg/feature.py")
    audit = root / "data" / "audit"
    audit.mkdir(parents=True)
    lane = {
        "lane_id": "lane-host-test", "status": "active",
        "goal_id": GOAL, "branch": "feat/host-test",
        "worktree": str(root.resolve()), "base_main_sha": base,
        "version": 1, "paths": ["src/llm_loop/pkg/feature.py"],
    }
    (audit / "lanes.jsonl").write_text(json.dumps(lane) + "\n")
    return root, base


def test_host_rederives_exact_git_tree_and_lane(live_repo):
    root, base = live_repo
    ctx = host.inspect_repo(
        root, goal=GOAL, req=REQ, base=base,
        message_sha256="d" * 64, owner_uid=os.geteuid(),
    )
    assert ctx["tree"] == _git(root, "write-tree")
    assert ctx["lane_id"] == "lane-host-test"
    assert ctx["paths"] == ["src/llm_loop/pkg/feature.py"]


def test_host_tree_requires_no_write_to_owner_git_index_or_objects(live_repo):
    root, base = live_repo
    expected = _git(root, "write-tree")
    git_dir = root / ".git"
    objects = git_dir / "objects"
    original_git_mode = git_dir.stat().st_mode & 0o777
    original_objects_mode = objects.stat().st_mode & 0o777
    try:
        # Simulate an independent UID: reading is allowed, writing index.lock
        # or new tree objects into the developer's .git is not.
        git_dir.chmod(0o555)
        objects.chmod(0o555)
        ctx = host.inspect_repo(
            root, goal=GOAL, req=REQ, base=base,
            message_sha256="d" * 64, owner_uid=os.geteuid(),
        )
        assert ctx["tree"] == expected
        assert not (git_dir / "index.lock").exists()
    finally:
        objects.chmod(original_objects_mode)
        git_dir.chmod(original_git_mode)


def test_host_tree_in_linked_git_worktree(live_repo, tmp_path):
    root, base = live_repo
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "-q", "-b", "feat/host-linked", str(linked), base)
    source = linked / "src" / "llm_loop" / "pkg" / "feature.py"
    source.write_text("x = 3\n")
    _git(linked, "add", "src/llm_loop/pkg/feature.py")
    tree, paths = host._staged_tree_readonly(linked, owner_uid=os.geteuid())
    assert tree == _git(linked, "write-tree")
    assert paths == ["src/llm_loop/pkg/feature.py"]


def test_host_snapshot_paths_include_both_rename_sides_and_unicode(live_repo):
    root, _ = live_repo
    (root / "docs").mkdir(exist_ok=True)
    _git(root, "mv", "src/llm_loop/pkg/feature.py", "docs/重命名.py")
    tree, paths = host._staged_tree_readonly(root, owner_uid=os.geteuid())
    assert tree == _git(root, "write-tree")
    assert set(paths) == {"src/llm_loop/pkg/feature.py", "docs/重命名.py"}


def test_host_detects_index_inplace_change_even_if_mtime_restored(
    live_repo, monkeypatch
):
    root, _ = live_repo
    index = root / ".git" / "index"
    original_run = host.subprocess.run
    triggered = False

    def change_index_during_tree(args, **kwargs):
        nonlocal triggered
        if args[-1] == "write-tree" and not triggered:
            triggered = True
            previous = index.stat()
            changed = bytearray(index.read_bytes())
            changed[-1] ^= 1
            index.write_bytes(changed)
            os.utime(index, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        return original_run(args, **kwargs)

    monkeypatch.setattr(host.subprocess, "run", change_index_during_tree)
    with pytest.raises(host.HostHoldError, match="host_git_index_changed"):
        host._staged_tree_readonly(root, owner_uid=os.geteuid())
    assert triggered


def test_host_denies_protected_change_already_committed_since_base(live_repo):
    root, base = live_repo
    protected = root / "scripts" / "ci_gate.sh"
    protected.parent.mkdir(exist_ok=True)
    protected.write_text("echo unreviewed\n")
    _git(root, "add", "scripts/ci_gate.sh")
    _git(root, "commit", "-qm", "unreviewed protected change")
    feature = root / "src" / "llm_loop" / "pkg" / "feature.py"
    feature.write_text("x = 4\n")
    _git(root, "add", "src/llm_loop/pkg/feature.py")
    with pytest.raises(host.HostHoldError, match="protected_change_requires_full_r9"):
        host.inspect_repo(
            root, goal=GOAL, req=REQ, base=base,
            message_sha256="d" * 64, owner_uid=os.geteuid(),
        )


def test_host_denies_head_change_during_private_index_snapshot(
    live_repo, monkeypatch
):
    root, base = live_repo
    original = host._staged_tree_readonly
    new_head = _git(root, "commit-tree", _git(root, "write-tree"),
                    "-p", base, "-m", "alternate head")

    def change_head_after_snapshot(*args, **kwargs):
        result = original(*args, **kwargs)
        _git(root, "update-ref", "HEAD", new_head)
        return result

    monkeypatch.setattr(host, "_staged_tree_readonly", change_head_after_snapshot)
    with pytest.raises(host.HostHoldError, match="host_git_refs_changed"):
        host.inspect_repo(
            root, goal=GOAL, req=REQ, base=base,
            message_sha256="d" * 64, owner_uid=os.geteuid(),
        )


def test_host_rejects_symlinked_object_store(live_repo):
    root, _ = live_repo
    objects = root / ".git" / "objects"
    saved = objects.with_name("objects.saved")
    objects.rename(saved)
    try:
        objects.symlink_to(saved.name, target_is_directory=True)
        with pytest.raises(host.HostHoldError, match="host_git_objects_untrusted"):
            host._staged_tree_readonly(root, owner_uid=os.geteuid())
    finally:
        objects.unlink(missing_ok=True)
        saved.rename(objects)


def test_host_rejects_git_alternate_object_injection(live_repo):
    root, _ = live_repo
    alternates = root / ".git" / "objects" / "info" / "alternates"
    alternates.parent.mkdir(exist_ok=True)
    alternates.write_text("/private/tmp/attacker-objects\n")
    with pytest.raises(host.HostHoldError, match="host_git_objects_untrusted"):
        host._staged_tree_readonly(root, owner_uid=os.geteuid())


def test_host_rejects_corrupted_base_tree_under_unchanged_oid(live_repo):
    root, base = live_repo
    candidate = _git(root, "write-tree")
    base_tree = _git(root, "rev-parse", f"{base}^{{tree}}")
    obj = root / ".git" / "objects" / base_tree[:2] / base_tree[2:]
    replacement = root / ".git" / "objects" / candidate[:2] / candidate[2:]
    original = obj.read_bytes()
    mode = obj.stat().st_mode & 0o777
    try:
        obj.chmod(0o644)
        obj.write_bytes(replacement.read_bytes())
        with pytest.raises(host.HostHoldError, match="host_git_object_integrity_failed"):
            host._verified_protected_tree_unchanged(
                base=base, candidate=candidate,
                git_cmd=["/usr/bin/git", "-C", str(root)],
                env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"},
            )
    finally:
        obj.write_bytes(original)
        obj.chmod(mode)


@pytest.mark.parametrize("corrupt_kind", ["blob", "nested_tree"])
def test_host_rejects_corrupted_protected_object_closure(live_repo, corrupt_kind):
    root, _ = live_repo
    protected = root / "scripts" / "subdir" / "keep.sh"
    protected.parent.mkdir(parents=True)
    protected.write_text("echo protected\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "protected baseline")
    base = _git(root, "rev-parse", "HEAD")
    candidate = _git(root, "write-tree")
    if corrupt_kind == "blob":
        original_oid = _git(root, "rev-parse", "HEAD:scripts/subdir/keep.sh")
        replacement_oid = _git(root, "rev-parse", "HEAD:src/llm_loop/pkg/feature.py")
    else:
        original_oid = _git(root, "rev-parse", "HEAD:scripts/subdir")
        replacement_oid = _git(root, "rev-parse", "HEAD:src/llm_loop/pkg")
    objects = root / ".git" / "objects"
    original_path = objects / original_oid[:2] / original_oid[2:]
    replacement_path = objects / replacement_oid[:2] / replacement_oid[2:]
    saved = original_path.read_bytes()
    mode = original_path.stat().st_mode & 0o777
    try:
        original_path.chmod(0o644)
        original_path.write_bytes(replacement_path.read_bytes())
        with pytest.raises(host.HostHoldError, match="host_git_object_integrity_failed"):
            host._verified_protected_tree_unchanged(
                base=base, candidate=candidate,
                git_cmd=["/usr/bin/git", "-C", str(root)],
                env={"PATH": "/usr/bin:/bin", "HOME": "/var/empty"},
            )
    finally:
        original_path.write_bytes(saved)
        original_path.chmod(mode)


def test_host_rejects_symlinked_git_metadata_and_info_directory(live_repo):
    root, _ = live_repo
    git_dir = root / ".git"
    saved_git = root / ".git.saved"
    git_dir.rename(saved_git)
    try:
        git_dir.symlink_to(saved_git.name, target_is_directory=True)
        with pytest.raises(host.HostHoldError, match="host_git_metadata_untrusted"):
            host._staged_tree_readonly(root, owner_uid=os.geteuid())
    finally:
        git_dir.unlink(missing_ok=True)
        saved_git.rename(git_dir)

    info = git_dir / "objects" / "info"
    info.mkdir(exist_ok=True)
    saved_info = info.with_name("info.saved")
    info.rename(saved_info)
    try:
        info.symlink_to(saved_info.name, target_is_directory=True)
        with pytest.raises(host.HostHoldError, match="host_git_objects_untrusted"):
            host._staged_tree_readonly(root, owner_uid=os.geteuid())
    finally:
        info.unlink(missing_ok=True)
        saved_info.rename(info)


def test_host_rejects_group_writable_or_symlinked_git_index(live_repo):
    root, base = live_repo
    index = root / ".git" / "index"
    original_mode = index.stat().st_mode & 0o777
    try:
        index.chmod(0o664)
        with pytest.raises(host.HostHoldError, match="host_git_index_untrusted"):
            host.inspect_repo(
                root, goal=GOAL, req=REQ, base=base,
                message_sha256="d" * 64, owner_uid=os.geteuid(),
            )
    finally:
        index.chmod(original_mode)
    saved = index.with_name("index.saved")
    index.rename(saved)
    try:
        index.symlink_to(saved.name)
        with pytest.raises(OSError):
            host._staged_tree_readonly(root, owner_uid=os.geteuid())
    finally:
        index.unlink(missing_ok=True)
        saved.rename(index)


@pytest.mark.parametrize("change", ["untracked", "unstaged", "protected", "case_protected", "base", "origin", "lane"])
def test_host_rejects_untrusted_git_or_lane_state(live_repo, change):
    root, base = live_repo
    if change == "untracked":
        (root / "extra.txt").write_text("unexpected")
    elif change == "unstaged":
        (root / "src/llm_loop/pkg/feature.py").write_text("x = 3\n")
    elif change == "protected":
        script = root / "scripts" / "ci_gate.sh"
        script.parent.mkdir()
        script.write_text("echo bypass\n")
        _git(root, "add", "scripts/ci_gate.sh")
    elif change == "case_protected":
        script = root / "ScRiPtS" / "ci_gate.sh"
        script.parent.mkdir()
        script.write_text("echo case bypass\n")
        _git(root, "add", "ScRiPtS/ci_gate.sh")
    elif change == "base":
        _git(root, "commit", "--allow-empty", "-qm", "remote main advanced")
        _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    elif change == "origin":
        _git(root, "remote", "set-url", "origin", "https://example.com/evil.git")
    elif change == "lane":
        lane = root / "data" / "audit" / "lanes.jsonl"
        lane.write_text(lane.read_text().replace("feat/host-test", "main"))
    with pytest.raises(host.HostHoldError):
        host.inspect_repo(
            root, goal=GOAL, req=REQ, base=base,
            message_sha256="d" * 64, owner_uid=os.geteuid(),
        )


def test_uninstalled_runtime_denied_without_host_uid():
    if os.geteuid() != host.HOST_UID:
        with pytest.raises(host.HostHoldError, match="independent_host_runtime_required"):
            host._require_installed()
