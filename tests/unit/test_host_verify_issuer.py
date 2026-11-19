"""Host verify receipt is a browser-approved, process-local reviewer effect."""

from __future__ import annotations

import hashlib
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
    _git,
    _parse_review,
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
    assert "frozen_diff_sha256=" in runner.started["task"]
    assert "+two" in runner.started["task"]
    return authority.request(lane_id=lane_id, child_id=out["child_id"], scope="focused PASS")


def human_issue(authority):
    return lambda row: authority.issue(row, approver="web:session:12345678")


def human_decide(store, rec, authority):
    return store.decide(
        rec["id"], "approved", decided_by="web:session:12345678",
        channel="web_session", expected_sha256=rec["command_sha256"],
        issue_verify=human_issue(authority),
    )


def test_human_approved_host_issues_exact_receipt(host):
    authority, _, store, lane_id, _, audit = host
    rec = requested(host)
    assert rec["request_kind"] == "verify_receipt"
    assert not (audit / "verify_receipts.jsonl").exists()
    approved, reason = human_decide(store, rec, authority)
    assert reason == ""
    assert approved["verify_receipt_id"].startswith(lane_id + ":")
    row = load_receipts(audit / "verify_receipts.jsonl")[approved["verify_receipt_id"]]
    assert row["result"] == "pass"
    assert row["head_sha"] == authority._reviews["subagent-test-review"].head
    assert row["reviewer"] == "glm/glm-5.3-flash"
    assert row["evidence"].startswith("host-review:subagent-test-review:")
    assert f"request:{rec['id']}:approver:web:session:12345678" in row["evidence"]
    assert store.get(rec["id"])["token"] == ""
    assert human_decide(store, rec, authority)[0] is None
    assert len((audit / "verify_receipts.jsonl").read_text().splitlines()) == 1


def test_without_host_callback_cannot_mint_verify_token(host):
    _, _, store, _, _, audit = host
    rec = requested(host)
    approved, reason = store.decide(
        rec["id"], "approved", decided_by="web:session:12345678",
        channel="web_session",
    )
    assert approved is None and reason == "verify_receipt_requires_host_issuer"
    assert store.get(rec["id"])["status"] == "pending"
    assert not (audit / "verify_receipts.jsonl").exists()


def test_non_browser_decision_cannot_issue_even_with_host_callback(host):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    approved, reason = store.decide(
        rec["id"], "approved", decided_by="web:loopback",
        channel="loopback_unauthenticated", issue_verify=human_issue(authority),
    )
    assert approved is None and reason == "human_auth_required"
    with pytest.raises(HostVerifyError, match="human_browser_approval_required"):
        authority.issue(rec, approver="web:loopback")
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
        human_decide(store, rec, authority)
    assert store.get(rec["id"])["status"] == "pending"
    assert not (audit / "verify_receipts.jsonl").exists()


def test_symlink_receipt_target_rejected(host):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    victim = audit / "victim.txt"
    victim.write_text("do not touch", encoding="utf-8")
    (audit / "verify_receipts.jsonl").symlink_to(victim)
    with pytest.raises(OSError):
        human_decide(store, rec, authority)
    assert victim.read_text() == "do not touch"
    assert store.get(rec["id"])["status"] == "pending"


def test_hardlink_receipt_target_rejected(host):
    authority, _, store, _, _, audit = host
    rec = requested(host)
    victim = audit / "other-ledger.jsonl"
    victim.write_text("keep\n", encoding="utf-8")
    os.link(victim, audit / "verify_receipts.jsonl")
    with pytest.raises(PermissionError):
        human_decide(store, rec, authority)
    assert victim.read_text() == "keep\n"
    assert store.get(rec["id"])["status"] == "pending"


def test_review_changed_after_request_rejected(host):
    authority, runner, store, _, _, audit = host
    rec = requested(host)
    runner.p1 = 1
    with pytest.raises(HostVerifyError, match="review_p0_p1_blocked"):
        human_decide(store, rec, authority)
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
    app = build_app(engine=engine)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 51321))
    body = {"id": rec["id"], "decision": "approved", "expected_sha256": rec["command_sha256"]}
    blocked = client.post("/api/v1/escalation/review", json=body)
    assert blocked.status_code == 403 and blocked.json()["error"] == "human_auth_required"
    assert not (audit / "verify_receipts.jsonl").exists()
    client.cookies.set(SESSION_COOKIE_NAME, app.state.web_sessions.create(ttl_seconds=3600))
    ok = client.post("/api/v1/escalation/review", json=body)
    assert ok.status_code == 200, ok.text
    assert store.get(rec["id"])["status"] == "approved"
    assert load_receipts(audit / "verify_receipts.jsonl")


FENCE = "```"


def _review_payload(*, verdict="PASS", p0=0, p1=0, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40):
    return json.dumps({
        "gate": "merge", "verdict": verdict, "p0": p0, "p1": p1,
        "lane_id": lane_id, "base_sha": base, "head_sha": head,
    })


def test_review_accepts_one_terminal_fenced_json():
    answer = f"{FENCE}json\n{_review_payload()}\n{FENCE}"
    _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


def test_review_accepts_raw_json():
    _parse_review(_review_payload(), lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("prefix", [
    "审查通过，未发现 P0/P1 问题。\n",
    "Independent read-only review PASSed with no findings.\n",
])
def test_review_rejects_prose_prefix_even_if_pass(prefix):
    answer = f"{prefix}{FENCE}json\n{_review_payload()}\n{FENCE}"
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)



@pytest.mark.parametrize("prefix", [
    "导入链信任：回应了此前 REVISE 中的可信路径问题。\n未发现可成立的 P0/P1 问题。\n",
    "The previous REVISE findings were fixed. Current review: PASS.\n",
])
def test_review_rejects_historical_negative_verdict_prose(prefix):
    answer = f"{prefix}{FENCE}json\n{_review_payload()}\n{FENCE}"
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("prefix", [
    "verdict: REVISE\n",
    "结论：BLOCKED\n",
    "REJECTED: current candidate has issues.\n",
])
def test_review_rejects_explicit_current_negative_verdict(prefix):
    answer = f"{prefix}{FENCE}json\n{_review_payload()}\n{FENCE}"
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("answer", [
    # P1 negative repro 1: prose verdict contradicting the fenced JSON.
    "REVISE: P1=2 high severity defect.\n{fence}json\n{payload}\n{fence}",
    # P1 negative repro 2: extra contradictory JSON object ahead of the fence.
    '{{"gate":"merge","verdict":"REVISE","p1":2}}\n{fence}json\n{payload}\n{fence}',
    # Prose verdict without nonzero P0/P1 assignment is still a conflict.
    "BLOCKED: review found issues.\n{fence}json\n{payload}\n{fence}",
])
def test_review_rejects_conflicting_prefix(answer):
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer.format(payload=_review_payload(), fence=FENCE), lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("answer", [
    "Read-only review.\n{fence}json\n{payload}\n{fence}\nMore prose",
    "Read-only review.\n{fence}json\n{payload}\n{fence}\n{fence}json\n{payload}\n{fence}",
    "Read-only review.\n{fence}python\n{payload}\n{fence}",
    "Read-only review.\n{payload}",
    "Read-only review.\n{fence}json\n{payload}\n{fence}\nextra block marker {fence}",
])
def test_review_rejects_ambiguous_fenced_answer(answer):
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer.format(payload=_review_payload(), fence=FENCE), lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("changes,error", [
    ({"verdict": "REVISE"}, "review_identity_or_verdict_invalid"),
    ({"p0": 1}, "review_p0_p1_blocked"),
    ({"p1": 1}, "review_p0_p1_blocked"),
    ({"p0": True}, "review_p0_p1_invalid"),
    ({"lane_id": "lane-ffffffff"}, "review_identity_or_verdict_invalid"),
    ({"head": "c" * 40}, "review_identity_or_verdict_invalid"),
])
def test_review_fenced_identity_and_verdict_still_fail_closed(changes, error):
    answer = f"{FENCE}json\n" + _review_payload(**changes) + f"\n{FENCE}"
    with pytest.raises(HostVerifyError, match=error):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


def test_fenced_terminal_review_can_request_then_human_issue(host, monkeypatch):
    authority, runner, store, lane_id, _, audit = host
    original = runner.review_terminal_current

    def fenced_terminal(child_id, parent):
        terminal = original(child_id, parent)
        terminal["final_answer"] = (
            FENCE + "json\n" + terminal["final_answer"] + "\n" + FENCE
        )
        return terminal

    monkeypatch.setattr(runner, "review_terminal_current", fenced_terminal)
    rec = requested(host)
    assert rec["request_kind"] == "verify_receipt"
    assert not (audit / "verify_receipts.jsonl").exists()
    approved, reason = human_decide(store, rec, authority)
    assert reason == ""
    assert approved["verify_receipt_id"].startswith(lane_id + ":")
    assert load_receipts(audit / "verify_receipts.jsonl")[approved["verify_receipt_id"]]["result"] == "pass"


@pytest.mark.parametrize("prefix", [
    "The current verdict is REVISE due to a critical security flaw.",
    "Current review found P1 critical issue and must not merge.",
    "本次审查发现一个高危问题，不允许合并。",
    "The reviewer finds a security vulnerability; approval is denied.",
    "The previous REVISE findings were fixed. Current verdict is REVISE.",
    "Review: PASS. However, the candidate must not merge due to a security flaw.",
    "Reviewer notes: the current candidate has a blocking defect.",
    "No P0/P1 issues. But the code has a critical defect.",
    "Current review: PASS. This code is unsafe to merge.",
    "Current review: PASS. Do not approve this change.",
    "Review: PASS. This change is not ready to merge.",
    "Reviewer notes without a positive machine-verifiable conclusion.",
])
def test_review_rejects_semantic_negative_prefix_even_with_terminal_pass(prefix):
    answer = f"{prefix}\n{FENCE}json\n{_review_payload()}\n{FENCE}"
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)



@pytest.mark.parametrize("prefix", [
    "Previous PASS has been revoked. This candidate is dangerous to deploy.",
    "No P0/P1 issues found. However, the code is vulnerable to arbitrary file writes.",
    "审查通过，但存在严重漏洞，暂不能发布。",
    "Earlier REVISE remains unresolved. PASS would be incorrect.",
    "No P0/P1 issues. DO NOT SHIP this candidate.",
    "This review is PASS, but a privilege escalation was found.",
    "No P0/P1 issues. This patch is unsafe for production.",
    "No P0/P1 issues. Do not deploy the code.",
    "Previous REVISE remains valid. PASS is not warranted.",
    "No P0/P1 issues; critical exploit is still open.",
    "P1：2 处遗留问题，审查通过但不能合并。",
    "当前REVISE：代码有缺陷；审查通过是假象。",
])
def test_review_rejects_adversarial_contradictory_prose(prefix):
    answer = f"{prefix}\n{FENCE}json\n{_review_payload()}\n{FENCE}"
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("wrapped", [False, True])
def test_review_rejects_duplicate_json_keys(wrapped):
    payload = _review_payload()
    assert payload.endswith("}")
    payload = payload[:-1] + ', "verdict": "PASS"}'
    answer = f"{FENCE}json\n{payload}\n{FENCE}" if wrapped else payload
    with pytest.raises(HostVerifyError, match="review_not_structured"):
        _parse_review(answer, lane_id="lane-1234abcd", base="a" * 40, head="b" * 40)


@pytest.mark.parametrize("file_size,review_allowed", [
    (225_000, True),
    (260_000, True),
    (385_000, True),
    (399_000, True),
    (400_000, False),
])
def test_host_frozen_diff_has_separate_bounded_large_patch_budget(
    host, file_size, review_allowed,
):
    """Large PRs are reviewable; oversize diffs still HOLD, without receipts."""
    authority, runner, _, lane_id, _, audit = host
    lane = LaneStore(audit).get(lane_id)
    assert lane is not None
    worktree = Path(lane["worktree"])
    (worktree / "large.txt").write_text("x" * file_size + "\n", encoding="utf-8")
    git(worktree, "add", "large.txt")
    git(worktree, "commit", "-m", "add large review input")
    head = git(worktree, "rev-parse", "HEAD")
    LaneStore(audit).update(lane_id, expected_version=2, head_sha=head)

    # The default cap stays strict for all unrelated Git output.
    with pytest.raises(HostVerifyError, match="git_state_unavailable"):
        _git(worktree, "show", "HEAD:large.txt")

    if review_allowed:
        out = authority.start_review(lane_id)
        assert out["child_id"] == "subagent-test-review"
        assert len(runner.started["task"]) > 100_000
        assert runner.started["review_isolated"] is True
        assert runner.started["required_tools"] == ["read_file", "search_files"]
        frozen_diff = _git(
            worktree, "diff", "--no-ext-diff", "--no-color",
            lane["base_main_sha"], head, output_limit=400_000,
        )
        assert f"<frozen_diff>\n{frozen_diff}\n</frozen_diff>" in runner.started["task"]
        assert f"frozen_diff_sha256={hashlib.sha256(frozen_diff.encode()).hexdigest()}" in runner.started["task"]
    else:
        with pytest.raises(HostVerifyError, match="review_diff_too_large"):
            authority.start_review(lane_id)
        assert runner.started == {}
    assert not (audit / "verify_receipts.jsonl").exists()


@pytest.mark.parametrize("actual_binary", [False, True])
def test_host_binary_diff_guard_distinguishes_git_metadata_from_source_text(
    host, actual_binary,
):
    """Source code quoting Git's markers is safe; actual binary diffs HOLD."""
    authority, runner, _, lane_id, _, audit = host
    lane = LaneStore(audit).get(lane_id)
    assert lane is not None
    worktree = Path(lane["worktree"])
    if actual_binary:
        (worktree / "blob.bin").write_bytes(b"\x00\x01\x02")
        git(worktree, "add", "blob.bin")
    else:
        (worktree / "a.txt").write_text(
            "two\nGIT binary patch\nBinary files a/x and b/x differ\n",
            encoding="utf-8",
        )
        git(worktree, "add", "a.txt")
    git(worktree, "commit", "-m", "test binary marker handling")
    head = git(worktree, "rev-parse", "HEAD")
    LaneStore(audit).update(lane_id, expected_version=2, head_sha=head)

    if actual_binary:
        with pytest.raises(HostVerifyError, match="review_diff_unavailable_or_sensitive"):
            authority.start_review(lane_id)
        assert runner.started == {}
    else:
        out = authority.start_review(lane_id)
        assert out["child_id"] == "subagent-test-review"
        assert runner.started["review_isolated"] is True
        assert "+GIT binary patch" in runner.started["task"]
    assert not (audit / "verify_receipts.jsonl").exists()
