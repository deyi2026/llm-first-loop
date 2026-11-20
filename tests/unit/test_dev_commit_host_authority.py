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


@pytest.mark.parametrize("change", ["untracked", "unstaged", "protected", "base", "origin", "lane"])
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
