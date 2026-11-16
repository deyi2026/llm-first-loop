"""Host verify receipt is a browser-approved, process-local reviewer effect."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.core.run_context import (
    current_model_label,
    current_session_id,
    current_workspace_root,
)
from llm_loop.introspection.host_verify_issuer import (
    HostVerifyAuthority,
    HostVerifyError,
)
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.merge_queue import load_receipts
from llm_loop.tools.escalation import EscalationStore
from llm_loop.web import build_app
from llm_loop.web.auth import SESSION_COOKIE_NAME


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class FakeReviewRunner:
    verdict = "PASS"
    p0 = 0
    p1 = 0
    independent = True

    def __init__(self) -> None:
        self.started = {}
        self.facts = {}

    def start(self, **kwargs):
        self.started = kwargs
        self.started["review_workspace"] = current_workspace_root.get()
        return {"accepted": True, "child_id": "subagent-test-review", "model": "glm/glm-5.3-flash"}

    def review_terminal_current(self, child_id, parent):
        if child_id != "subagent-test-review" or parent != "owner-session":
            return None
        return {
            "review_isolated": self.independent,
            "final_answer": json.dumps({
                "gate": "merge", "verdict": self.verdict,
                "p0": self.p0, "p1": self.p1, **self.facts,
            }),
        }


@pytest.fixture
def host(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.org")
    git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    worktree = tmp_path / "lane"
    git(repo, "worktree", "add", "-b", "fix/host-verify-test", str(worktree))
    (worktree / "a.txt").write_text("two\n", encoding="utf-8")
    git(worktree, "add", "a.txt")
    git(worktree, "commit", "-m", "fix")
    head = git(worktree, "rev-parse", "HEAD")
    audit = tmp_path / "data" / "audit"
    store = LaneStore(audit)
    lane = store.create(
        branch="fix/host-verify-test", worktree=str(worktree),
        base_main_sha=base, goal_id="goal-test", paths=["a.txt"],
    )
    store.update(lane.lane_id, expected_version=1, status="verifying", head_sha=head)
    escalation = EscalationStore(audit / "escalation_requests.json")
    runner = FakeReviewRunner()
    runner.facts = {"lane_id": lane.lane_id, "base_sha": base, "head_sha": head}
    authority = HostVerifyAuthority(
        audit_dir=audit, repo_root=repo, runner=runner, escalation_store=escalation,
    )
    tok = current_session_id.set("owner-session")
    mtok = current_model_label.set("glm/glm-5.3-flash")
    try:
        yield authority, runner, escalation, lane.lane_id, repo, audit
    finally:
        current_model_label.reset(mtok)
        current_session_id.reset(tok)


def requested(host):
    authority, runner, store, lane_id, *_ = host
    out = authority.start_review(lane_id)
    assert out["child_id"] == "subagent-test-review"
    assert runner.started["review_isolated"] is True
    assert runner.started["required_tools"] == ["read_file", "search_files"]
    assert "execute_command" not in runner.started["required_tools"]
    assert Path(runner.started["review_workspace"]).name == "lane"
    return authority.request(lane_id=lane_id, child_id=out["child_id"], scope="focused PASS")


def test_human_approved_host_issues_exact_receipt(host):
    authority, _, store, lane_id, _, audit = host
    rec = requested(host)
    assert rec["request_kind"] == "verify_receipt"
    assert not (audit / "verify_receipts.jsonl").exists()
    approved, reason = store.decide(
        rec["id"], "approved", decided_by="web:session:test", channel="web_session",
        expected_sha256=rec["command_sha256"], issue_verify=authority.issue,
    )
    assert reason == ""
    assert approved["verify_receipt_id"].startswith(lane_id + ":")
    row = load_receipts(audit / "verify_receipts.jsonl")[approved["verify_receipt_id"]]
    assert row["result"] == "pass"
    assert row["head_sha"] == authority._reviews["subagent-test-review"].head
    assert row["reviewer"] == "glm/glm-5.3-flash"
    assert row["evidence"].startswith("host-review:subagent-test-review:")
    assert store.decide(rec["id"], "approved", issue_verify=authority.issue)[0] is None
    assert len((audit / "verify_receipts.jsonl").read_text().splitlines()) == 1


def test_without_host_callback_cannot_mint_verify_token(host):
    _, _, store, _, _, audit = host
    rec = requested(host)
    approved, reason = store.decide(rec["id"], "approved")
    assert approved is None and reason == "verify_receipt_requires_host_issuer"
    assert store.get(rec["id"])["status"] == "pending"
    assert not (audit / "verify_receipts.jsonl").exists()


@pytest.mark.parametrize("verdict,p0,p1,independent", [
    ("REVISE", 0, 0, True), ("PASS", 1, 0, True),
    ("PASS", 0, 1, True), ("PASS", 0, 0, False),
])
def test_reviewer_must_be_independent_pass(host, verdict, p0, p1, independent):
    authority, runner, _, lane_id, _, audit = host
    authority.start_review(lane_id)
    runner.verdict, runner.p0, runner.p1, runner.independent = verdict, p0, p1, independent
    with pytest.raises(HostVerifyError):
        authority.request(lane_id=lane_id, child_id="subagent-test-review")
    assert not (audit / "verify_receipts.jsonl").exists()


def test_base_advance_between_request_and_approval_fails_closed(host):
    authority, _, store, _, repo, audit = host
    rec = requested(host)
    (repo / "b.txt").write_text("advance\n", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-m", "main advanced")
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main"))
    with pytest.raises(HostVerifyError, match="lane_base_or_head_stale"):
        store.decide(rec["id"], "approved", issue_verify=authority.issue)
    assert store.get(rec["id"])["status"] == "pending"
    assert not (audit / "verify_receipts.jsonl").exists()


def test_symlink_receipt_target_rejected(host):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    victim = audit / "victim.txt"
    victim.write_text("do not touch", encoding="utf-8")
    (audit / "verify_receipts.jsonl").symlink_to(victim)
    with pytest.raises(OSError):
        store.decide(rec["id"], "approved", issue_verify=authority.issue)
    assert victim.read_text() == "do not touch"
    assert store.get(rec["id"])["status"] == "pending"


def test_hardlink_receipt_target_rejected(host):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    victim = audit / "other-ledger.jsonl"
    victim.write_text("keep\n", encoding="utf-8")
    os.link(victim, audit / "verify_receipts.jsonl")
    with pytest.raises(PermissionError):
        store.decide(rec["id"], "approved", issue_verify=authority.issue)
    assert victim.read_text() == "keep\n"
    assert store.get(rec["id"])["status"] == "pending"


def test_review_changed_after_request_rejected(host):
    authority, runner, store, _, _, audit = host
    rec = requested(host)
    runner.p1 = 1
    with pytest.raises(HostVerifyError, match="review_p0_p1_blocked"):
        store.decide(rec["id"], "approved", issue_verify=authority.issue)
    assert store.get(rec["id"])["status"] == "pending"
    assert not (audit / "verify_receipts.jsonl").exists()


def test_browser_auth_required_then_host_issue(host, build_test_engine, isolated_data_dir, monkeypatch):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    # Route uses LFL_DATA_DIR; bind it to the fixture's own signed request store.
    monkeypatch.setenv("LFL_DATA_DIR", str(audit.parent))
    monkeypatch.delenv("WEB_AUTH_REQUIRE", raising=False)
    monkeypatch.delenv("WEB_ORIGIN_ALLOWLIST", raising=False)
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    engine, _ = build_test_engine([{"content": "ok"}])
    engine.host_verify_authority = authority
    client = TestClient(build_app(engine=engine), base_url="http://127.0.0.1", client=("127.0.0.1", 51321))
    body = {"id": rec["id"], "decision": "approved", "expected_sha256": rec["command_sha256"]}
    blocked = client.post("/api/v1/escalation/review", json=body)
    assert blocked.status_code == 403 and blocked.json()["error"] == "human_auth_required"
    assert not (audit / "verify_receipts.jsonl").exists()
    client.cookies.set(SESSION_COOKIE_NAME, client.app.state.web_sessions.create(ttl_seconds=3600))
    ok = client.post("/api/v1/escalation/review", json=body)
    assert ok.status_code == 200, ok.text
    assert store.get(rec["id"])["status"] == "approved"
    assert load_receipts(audit / "verify_receipts.jsonl")
