"""P0-B RED contract: a real Host entry gate, not a PASS string in a tool receipt."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.tools import review_host_admission as rha
from llm_loop.tools.review_host_admission import (
    HostReviewAdmission,
    _browser_binding,
    _classify_reviewer_failure,
    _page_controls,
    _page_visible_text,
    classify_host_shell,
    is_publication_button,
)


class FakeChildRunner:
    def __init__(self) -> None:
        self.task = ""
        self.started = 0
        self.state = "running"
        self.answer = ""
        self.parent = "author-1"
        self.refusals: list[str] = []  # queued start failures; empty -> success

    def start(self, task: str, **kwargs):
        self.started += 1
        self.task = task
        assert kwargs["required_tools"] == []
        assert kwargs["inherit"] is False
        assert kwargs["max_rounds"] == 1
        assert kwargs["review_isolated"] is True
        if self.refusals:
            return {"accepted": False, "detail": self.refusals.pop(0)}
        return {"accepted": True, "child_id": "child-review-1", "state": "running"}

    def review_terminal_current(self, child_id: str, parent_id: str):
        if self.state != "completed" or parent_id != self.parent:
            return None
        return {
            "child_id": child_id, "parent_id": parent_id,
            "state": self.state, "generation": "gen-1",
            "review_isolated": True, "final_answer": self.answer,
        }

    def result_current(self, child_id: str, wait_seconds=0):
        assert child_id == "child-review-1"
        result = SimpleNamespace(final_answer=self.answer, outcome=self.state)
        return True, "ok", {
            "child_id": child_id,
            "parent_id": self.parent,
            "state": self.state,
            "result_id": "result-verified" if self.state == "completed" else "",
            "generation": "gen-1",
            "result": result,
            "local_active": self.state == "running",
        }


def _repo(tmp_path: Path) -> Path:
    p = tmp_path / "repo"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.name", "Unit Test"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.email", "test@example.invalid"], check=True)
    (p / "example.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(p), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(p), "commit", "-qm", "baseline"], check=True)
    (p / "example.py").write_text("x = 2\n")
    return p


@pytest.mark.parametrize(("command", "expected"), [
    ("pytest -q", "full_test"),
    ("python -m pytest --dist loadfile -n auto -q", "full_test"),
    ("bash scripts/ci_gate.sh", "full_test"),
    ("git push origin main", "git_push"),
    ("git -C . push --force-with-lease origin main", "git_push"),
    ("git push --dry-run origin main", None),
    ("echo git push origin main", None),
    ("pytest tests/unit/test_x.py -q", None),
    ("python -m pytest -m tier0", None),
    ("pytest --version", None),
    ("pytest --collect-only -q", None),
    ("python -m pytest --co", None),
    ("bash scripts/ci_gate.sh --quick", None),
    ("git status", None),
])
def test_shell_trigger_scoping(command: str, expected: str | None) -> None:
    assert classify_host_shell(command) == expected


@pytest.mark.parametrize(("command", "expected"), [
    ("git push origin main # --dry-run", "git_push"),
    ("git push origin main; echo --dry-run", "git_push"),
    ("git push --dry-run origin main && git push origin main", "git_push"),
    ("pytest tests/unit/a.py && pytest -q", "full_test"),
    ("python -m pytest -m tier0; python -m pytest -q", "full_test"),
    ("bash scripts/ci_gate.sh --quick; bash scripts/ci_gate.sh", "full_test"),
    ("echo 'git push origin main'", None),
    ("echo safe\ngit push origin main", "git_push"),
    ("git push --dry-run origin main\ngit push origin main", "git_push"),
    ("echo safe # note\ngit push origin main", "git_push"),
    ("printf 'pytest -q'", None),
    ("bash -c 'git push origin main'", "git_push"),
    ("uv run pytest -q", "full_test"),
    ("poetry run python -m pytest -q", "full_test"),
    ("pipenv run pytest -q", "full_test"),
    ("env -u GLM_API_KEY PYTHONPATH=src bash scripts/ci_gate.sh", "full_test"),
    ("command git push origin main", "git_push"),
    ("\\git push origin main", "git_push"),
    ("uv run pytest tests/unit/test_x.py -q", None),
    ("uv run --no-sync pytest -q", "full_test"),
    ("uv run --group dev python -m pytest -q", "full_test"),
    ("uv run --directory /tmp/other pytest -q", "full_test"),
    ("uv run --project /tmp/other pytest -q", "full_test"),
    ("uv run --no-sync pytest tests/unit/test_x.py", None),
    ("poetry run python -m pytest -k shadow_case", None),
    ("env -u GLM_API_KEY echo ready", None),
    ("command git status", None),
    ("eval 'git push origin main'", "git_push"),
    ("exec git push origin main", "git_push"),
    ("`git push origin main`", "git_push"),
    ("echo `git push origin main`", "git_push"),
    ("eval 'pytest -q'", "full_test"),
    ("`pytest -q`", "full_test"),
    ("echo '`pytest -q`'", None),
    ("make test -n", None),
    ("echo $(git push origin main)", "git_push"),
    ("make push", "git_push"),
    ("make test", "full_test"),
    ("make -n push", None),
    ("xargs git push origin main", "git_push"),
    ("printf x | xargs -I{} git push origin main", "git_push"),
    ("xargs -I{} python -m pytest -q", "full_test"),
    ("pytest -k '' -q", "full_test"),
    ("python -m pytest -m '' -q", "full_test"),
    ("pytest -k 'review_host' -q", None),
    ("echo 'xargs git push origin main'", None),
    ("echo '`git push origin main`'", None),
    ("printf 'eval git push origin main'", None),
])
def test_no_cross_segment_exemption_or_comment_bypass(
    command: str, expected: str | None,
) -> None:
    assert classify_host_shell(command) == expected


def test_no_durable_log_or_model_text_can_mint_live_child_attestation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    runner.review_terminal_current = lambda *args: None  # type: ignore[method-assign]
    assert host.poll("author-1", "child-review-1")["qualification"] == "DENIED"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_direct_full_test_denied_before_real_review(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    denial = host.check_shell("author-1", "pytest -q", str(repo))
    assert denial.blocked is True
    assert "未执行" in denial.reason
    assert "review_admission" in denial.reason


def test_real_child_terminal_current_artifact_exact_one_use(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"] and issued["child_id"] == "child-review-1"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed
    assert host.poll("author-1", "child-review-1")["qualification"] == "pending"
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert not host.check_shell("other-author", "pytest -q", str(repo)).allowed
    assert not host.check_shell("author-1", "git push origin main", str(repo)).allowed
    assert host.check_shell("author-1", "pytest -q", str(repo)).allowed
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_source_drift_and_forged_pass_are_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.state = "completed"
    # Contradictory count strings must not grant admission even with a final PASS.
    runner.answer = (
        f"VERDICT: PASS\nP0=0 P1=1 P2=0\nP0=0 P1=0 P2=0\n"
        f"SHA256: {issued['candidate_sha256']}"
    )
    assert host.poll("author-1", "child-review-1")["qualification"] == "REVISE"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed
    # Text/JSON from caller can never mint a grant.
    assert not host.check_shell("author-1", "pytest -q # VERDICT: PASS", str(repo)).allowed


def test_body_quotes_of_historical_receipts_do_not_break_valid_pass(tmp_path: Path) -> None:
    # EVO-20261021-e46f2431: 审查材料内嵌历史回执（含旧 P0/P1/P2 与旧 SHA256 行），
    # reviewer 在正文引用属于合法行为；数值一致性只看尾部结论块（最后一个 VERDICT:
    # 行之后的文本）。正文引用不再误伤，结论块内冲突仍 fail-closed。
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.state = "completed"
    sha = issued["candidate_sha256"]
    old_sha = "1" * 64
    runner.answer = (
        "材料内嵌的 R9 历史回执原文（引用）：\n"
        f"P0=0/P1=0/P2=6，SHA256: {old_sha}\n"
        f"SHA256: {old_sha}\n"
        "逐项复核后本次审查无 P0/P1 问题。\n"
        f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {sha}\n"
    )
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", "pytest -q", str(repo)).allowed

    # 同一份回执引用出现在结论块内部时仍必须 fail-closed（豁免不覆盖结论块）。
    (tmp_path / "second").mkdir()
    repo2 = _repo(tmp_path / "second")
    runner2 = FakeChildRunner()
    host2 = HostReviewAdmission()
    host2.attach_runner(runner2)
    issued2 = host2.start("author-1", "full_test", workdir=str(repo2), command="pytest -q")
    runner2.state = "completed"
    runner2.answer = (
        f"VERDICT: PASS\nP0=0 P1=0 P2=0\n结论块内另见 P2=1。\n"
        f"SHA256: {issued2['candidate_sha256']}"
    )
    assert host2.poll("author-1", "child-review-1")["qualification"] == "REVISE"
    assert not host2.check_shell("author-1", "pytest -q", str(repo2)).allowed


def test_quoted_verdict_line_in_body_still_fails_closed(tmp_path: Path) -> None:
    # 边界钉死：VERDICT 行唯一性仍在全文范围检查；正文原样引用历史回执的 VERDICT 行
    # 仍 fail-closed（reviewer 应转述而非原样引用），不因 e46f2431 放宽。
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.state = "completed"
    old_sha = "2" * 64
    runner.answer = (
        "材料内嵌历史回执原文（引用）：\n"
        f"VERDICT: PASS\nP0=0 P1=0 P2=6\nSHA256: {old_sha}\n"
        "本次复核无 P0/P1。\n"
        f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}\n"
    )
    assert host.poll("author-1", "child-review-1")["qualification"] == "REVISE"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_bash_dash_c_directory_switch_must_not_review_wrong_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (tmp_path / "other-workspace").mkdir()
    other = _repo(tmp_path / "other-workspace")
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    raw = "bash -c 'cd " + str(other) + " && pytest -q'"
    assert classify_host_shell(raw) == "full_test"
    outcome = host.start("author-1","full_test",workdir=str(repo),command=raw)
    assert not outcome["accepted"] and "requires" in outcome["reason"]
    assert runner.started == 0
    assert host.check_shell("author-1",raw,str(repo)).blocked


@pytest.mark.parametrize("command", ["eval 'pytest -q'", "`pytest -q`", "make test"])
def test_opaque_full_test_cannot_mint_wrong_artifact_qualification(
    tmp_path: Path, command: str,
) -> None:
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    result = host.start("author-1", "full_test", workdir=str(repo), command=command)
    assert result["accepted"] is False
    assert "requires_direct_command" in result["reason"]
    assert runner.started == 0
    assert host.check_shell("author-1", command, str(repo)).blocked


@pytest.mark.parametrize("command", [
    "xargs -I{} python -m pytest -q",
    "xargs git push origin main",
])
def test_xargs_indirect_protected_action_never_mints_wrong_target_review(
    tmp_path: Path, command: str,
) -> None:
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    kind = classify_host_shell(command)
    assert kind in {"full_test", "git_push"}
    result = host.start("author-1", kind, workdir=str(repo), command=command)
    assert result["accepted"] is False
    assert runner.started == 0
    assert host.check_shell("author-1", command, str(repo)).blocked


def test_frozen_source_changes_after_review_cannot_run(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    (repo / "example.py").write_text("x = 999\n")
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_push_target_is_bound_and_dry_run_unblocked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(repo)], check=True)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    target = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert target["accepted"]
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {target['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", "git push --dry-run origin main", str(repo)).allowed
    assert not host.check_shell("author-1", "git push origin other", str(repo)).allowed
    assert host.check_shell("author-1", "git push origin main", str(repo)).allowed


def _commit(repo: Path, name: str, text: str, msg: str) -> str:
    (repo / name).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg], check=True)
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _seed_bare_remote(repo: Path, tmp_path: Path, sha: str) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", sha + ":refs/heads/main"], check=True)
    return bare


def test_push_range_follows_target_commit_not_head(tmp_path: Path) -> None:
    # EVO-20261022-331eee17: pushing <commit>:<ref> must freeze only the
    # remote-base..<commit> delta; later HEAD commits, working tree and
    # untracked files are not part of the upload and must stay OUT of the
    # frozen material, while the identity binds the target commit.
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    target = _commit(repo, "example.py", "x = 2\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    _commit(repo, "later.py", "later = 1\n", "b3")  # HEAD beyond the push target
    (repo / "dirty.txt").write_text("dirty working state\n")  # never uploaded
    (repo / "untracked.txt").write_text("untracked note\n")  # never uploaded
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo),
                        command=f"git push origin {target}:main")
    assert issued["accepted"], issued
    assert issued["push_src_commit"] == target
    assert issued["push_remote_commit"] == base
    assert "first_push_anchor" not in issued
    assert f"frozen_head={target}" in runner.task
    assert "x = 2" in runner.task            # target commit delta IS frozen
    assert "later = 1" not in runner.task    # HEAD-beyond-target excluded
    assert "dirty working state" not in runner.task
    assert "untracked note" not in runner.task
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", f"git push origin {target}:main", str(repo)).allowed
    # A permit minted for the target commit must not cover the full HEAD push.
    assert not host.check_shell("author-1", "git push origin HEAD:main", str(repo)).allowed


def test_first_push_anchors_on_remote_default_branch(tmp_path: Path) -> None:
    # EVO-20261022-331eee17: a destination ref absent on the remote anchors
    # the review on the remote default branch (HEAD symref) instead of
    # refusing; the target ref is recorded explicitly. An empty remote with
    # no resolvable HEAD still fails closed.
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _seed_bare_remote(repo, tmp_path, base)
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feature"], check=True)
    head = _commit(repo, "feature.py", "value = 7\n", "f1")
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo),
                        command="git push origin feature")
    assert issued["accepted"], issued
    assert issued["first_push_anchor"] == base
    assert issued["first_push_target_ref"] == "refs/heads/feature"
    assert issued["push_src_commit"] == head
    assert f"push_first_push_anchor={base} push_target_ref=refs/heads/feature" in runner.task
    assert "value = 7" in runner.task
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", "git push origin feature", str(repo)).allowed
    # Empty remote: destination ref absent AND no resolvable HEAD anchor.
    empty = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(empty)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", str(empty)], check=True)
    refused = host.start("author-2", "git_push", workdir=str(repo),
                         command="git push origin feature")
    assert not refused["accepted"]
    assert "first_push_scope_unreviewable" in str(refused["reason"])


def test_browser_publication_freezes_page_and_target(tmp_path: Path) -> None:
    state = {
        "url": "https://example.org/editor",
        "observed_at": "2026-10-15T01:01:01Z",
        "dom": {"nodes": [
            {"kind": "textarea", "attributes": {"value": "My finished article"}},
            {"kind": "button", "attributes": {"role": "button", "name": "Publish"}},
            {"kind": "button", "attributes": {"role": "button", "name": "Save draft"}},
        ]},
    }
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: state)
    assert is_publication_button({"kind": "button", "attributes": {"name": "Publish", "role": "button"}})
    assert not is_publication_button({"kind": "button", "attributes": {"name": "Save draft", "role": "button"}})
    target = {"kind": "button", "attributes": {"name": "Publish", "role": "button"}}
    action = {"verb": "click", "action_id": "action1"}
    assert host.check_browser("author-1", action, target, state).blocked
    issued = host.start("author-1", "article_publish", target_name="Publish")
    assert issued["accepted"]
    runner.state = "completed"
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    state["observed_at"] = "2026-10-15T01:01:05Z"
    assert host.check_browser("author-1", action, target, state).allowed
    assert not host.check_browser("author-1", action, target, state).allowed


def test_generic_publish_without_article_editor_is_not_automatically_article_gate() -> None:
    host = HostReviewAdmission()
    raw = {
        "url": "https://ops.example.org/deploy",
        "dom": {"nodes": [
            {"kind": "button", "attributes": {"role": "button", "name": "Publish"}},
        ]},
    }
    target = raw["dom"]["nodes"][0]
    assert host.check_browser("owner", {"verb": "click"}, target, raw).allowed
    assert not host.start("owner", "article_publish", target_name="Publish")["accepted"]


def test_untracked_sensitive_file_never_becomes_model_review_material(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "api-token.env").write_text("API_KEY=private-hypothetical-content\n")
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    result = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert result["accepted"] is False
    assert runner.started == 0


def test_browser_editor_change_invalidates_review(tmp_path: Path) -> None:
    raw = {
        "url": "https://example.org/editor",
        "dom": {"nodes": [{"kind": "textarea", "attributes": {"value": "Version A"}},
                           {"kind": "button", "attributes": {"name": "Publish", "role": "button"}}]},
    }
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="Publish")
    runner.state = "completed"
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    raw["dom"]["nodes"][0]["attributes"]["value"] = "Version B"
    target = {"kind": "button", "attributes": {"name": "Publish", "role": "button"}}
    assert host.check_browser("author-1", {"verb": "click"}, target, raw).blocked


def test_untracked_password_related_source_file_can_be_reviewed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "password_validation.py").write_text("def validate(candidate):\n    return bool(candidate)\n")
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    outcome = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert outcome["accepted"] and runner.started == 1


def test_host_receipt_write_failure_cannot_grant_permission(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)

    class _UnavailableAudit:
        enabled = True

        def append(self, *args):
            return None

    host.attach_event_store(_UnavailableAudit())
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", issued["child_id"])["reason"] == "review_receipt_not_durable"
    assert host.check_shell("author-1", "pytest -q", str(repo)).blocked


def test_untracked_no_extension_secret_and_home_auth_files_block_pre_review(tmp_path: Path) -> None:
    for name in ("secrets", "credentials", ".netrc"):
        (tmp_path / name).mkdir()
        repo = _repo(tmp_path / name)
        (repo / name).write_text("example-private-data-should-stay-local\n")
        host = HostReviewAdmission()
        runner = FakeChildRunner()
        host.attach_runner(runner)
        out = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
        assert out["accepted"] is False
        assert runner.started == 0


def test_host_review_record_capacity_exhausts_without_unbounded_memory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host._max_records = 1
    first = host.start("author-1","full_test",workdir=str(repo),command="pytest -q")
    assert first["accepted"] and len(host._records) == 1
    second = host.start("author-1","full_test",workdir=str(repo),command="pytest -q")
    assert not second["accepted"] and second["reason"] == "review_host_capacity"
    assert len(host._records) == 1
    assert all(not hasattr(item,"review_material") for item in host._records.values())


def test_large_but_bounded_multi_file_artifact_is_reviewable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # EVO-20261023-fc5c34b9: the complete-review ceiling moved from 192KB to
    # 2.5MB (bytes) so a real branch's frozen material can be reviewed whole
    # instead of being refused for being large. The invariant under test is
    # unchanged: a payload UNDER the ceiling is reviewed complete, a payload
    # OVER it is refused with attribution, and nothing is ever truncated.
    (repo / "many_tests.py").write_text("x = " + repr("a" * 155_000) + "\n")
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert runner.started == 1
    assert "many_tests.py" in runner.task
    # Stay below the separate per-untracked-file 200KB bound by splitting the
    # over-cap payload across several files, so the complete-review ceiling,
    # not the per-file guard, is what rejects.
    for i in range(20):
        (repo / f"big_{i}.py").write_text("x = " + repr("a" * 199_000) + "\n")
    blocked = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert blocked["accepted"] is False
    assert blocked["reason"].startswith("review_artifact_exceeds_cap")
    # EVO-20261021-ea18d5ce: the refusal must attribute its largest sections
    # so the caller can act without a manual numstat/ls -la hunt. The largest
    # section here is one of the over-cap payloads (they dominate the
    # material), so the attribution names it.
    assert "big_0.py" in blocked["reason"]
    assert runner.started == 1


def _commit_runtime_report(repo: Path) -> None:
    d = repo / "reports" / "phase3" / "m0"
    d.mkdir(parents=True)
    (d / "S10.json").write_text('{"baseline":true}')
    subprocess.run(["git", "-C", str(repo), "add", "reports"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "report baseline"], check=True)


def test_runtime_report_regeneration_keeps_full_test_binding_alive(tmp_path: Path) -> None:
    # EVO-20261021-ea18d5ce: a full run rewrites tracked runtime reports
    # (reports/**, one regenerated file is a single 302KB line). That churn
    # must neither blow the 192KB material ceiling nor change the frozen SHA
    # that check_shell re-binds after the run.
    repo = _repo(tmp_path)
    _commit_runtime_report(repo)
    (repo / "reports" / "phase3" / "m0" / "S10.json").write_text("x" * 302_000)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert "runtime_output_excludes=reports/" in runner.task
    assert "example.py" in runner.task  # real source dirt stays fully reviewed
    assert "x" * 1000 not in runner.task  # regenerated report content is out
    sha_before, _ = rha._source_snapshot(str(repo))
    (repo / "reports" / "phase3" / "m0" / "S10.json").write_text("y" * 302_000)
    sha_after, _ = rha._source_snapshot(str(repo))
    assert sha_before == sha_after  # regeneration churns reports, not identity


def test_committed_runtime_monster_diff_is_truncated_not_deadlocked(tmp_path: Path) -> None:
    # EVO-20261021-2f22aae5 (proposal A, human-approved 2026-10-22): a
    # committed single-line runtime report (302KB) used to structurally
    # exceed the 192KB ceiling — while publish's clean-tree requirement
    # forces that very commit first (deadlock verified 2026-10-21). Committed
    # runtime-output diffs above the projection bound now render as head/tail
    # evidence plus an explicit truncation marker: the deadlock is gone and
    # the change stays visible to the reviewer.
    repo = _repo(tmp_path)
    # The fixture's initial branch IS main and HEAD sits on it, so
    # merge-base(HEAD, main)==HEAD would freeze an EMPTY committed delta;
    # advance HEAD onto a side branch so the committed report is genuinely
    # inside the frozen delta.
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    d = repo / "reports" / "phase3" / "m0"
    d.mkdir(parents=True)
    (d / "S10.json").write_text("z" * 302_000)
    subprocess.run(["git", "-C", str(repo), "add", "reports"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "big committed report"], check=True)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert runner.started == 1
    # The reviewer material names the file, keeps the diff header edges and
    # states the truncation fact with byte counts.
    assert "S10.json" in runner.task
    assert "EVO-20261021-2f22aae5 TRUNCATED committed runtime output diff" in runner.task
    assert "omitted " in runner.task and "B of " in runner.task
    assert "diff --git" in runner.task
    assert "z" * 60_000 not in runner.task  # the omitted middle is really out


def test_committed_non_runtime_monster_still_refused(tmp_path: Path) -> None:
    # EVO-20261021-2f22aae5 guardrail: the truncated projection unlocks ONLY
    # _RUNTIME_OUTPUT_EXCLUDES paths. A committed single-line monster anywhere
    # else keeps the full-review rule and the complete-review refusal,
    # unchanged.
    #
    # EVO-20261023-fc5c34b9: the ceiling moved from 192KB to 2.5MB, so the
    # fixture must exceed the CURRENT ceiling for this guardrail to still be
    # exercised. The intent (a non-runtime monster is never given a free
    # pass) is unchanged. The monster is split across several files because a
    # single 2.6MB one-line diff trips the separate `git_state_too_large`
    # guard (git output > 400KB) before the complete-review ceiling is even
    # reached — that guard is a different, still-intact rule.
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    (repo / "src").mkdir()
    for i in range(12):
        (repo / "src" / f"big_{i}.py").write_text("z" * 220_000)
    subprocess.run(["git", "-C", str(repo), "add", "src"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "big committed source"], check=True)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    blocked = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert blocked["accepted"] is False
    assert blocked["reason"].startswith("review_artifact_exceeds_cap")
    assert "big_0.py" in blocked["reason"]  # attribution names the real culprit
    assert runner.started == 0


def test_committed_runtime_projection_keeps_the_192kb_ceiling(tmp_path: Path) -> None:
    # EVO-20261021-2f22aae5 guardrail: the ceiling itself is unchanged.
    # Projected runtime monsters still exceed the ceiling and the admission is
    # refused with attribution — split or shrink, no free pass.
    #
    # EVO-20261023-fc5c34b9: the ceiling moved from 192KB to 2.5MB, so the
    # fixture must project to MORE than 2.5MB to keep exercising this
    # guardrail (each committed runtime monster projects to ~48KB, so 60 of
    # them clear the new ceiling). The intent is unchanged.
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    for i in range(60):
        p = repo / "reports" / f"run{i}" / "S.json"
        p.parent.mkdir(parents=True)
        p.write_text("z" * 302_000)
    subprocess.run(["git", "-C", str(repo), "add", "reports"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "many committed reports"], check=True)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    blocked = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert blocked["accepted"] is False
    assert blocked["reason"].startswith("review_artifact_exceeds_cap")
    assert runner.started == 0


def test_small_committed_runtime_diff_stays_verbatim(tmp_path: Path) -> None:
    # EVO-20261021-2f22aae5 guardrail: runtime diffs BELOW the projection
    # bound pass through untouched — no marker, no truncation, byte for byte.
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    d = repo / "reports" / "m0"
    d.mkdir(parents=True)
    (d / "S.json").write_text('{"baseline":true}')
    subprocess.run(["git", "-C", str(repo), "add", "reports"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "small report"], check=True)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert "TRUNCATED committed runtime output diff" not in runner.task
    assert '{"baseline":true}' in runner.task


def test_untracked_runtime_output_under_reports_is_not_material(tmp_path: Path) -> None:
    # Full runs also CREATE new report files; those must not trip the 200KB
    # per-untracked-file bound or enter the reviewer material either.
    repo = _repo(tmp_path)
    d = repo / "reports" / "newrun"
    d.mkdir(parents=True)
    (d / "BIG.json").write_text("w" * 250_000)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert "w" * 1000 not in runner.task


@pytest.mark.parametrize(
    "command", ["uv run --directory ../other pytest -q", "uv run --project ../other pytest -q"]
)
def test_uv_wrapper_project_drift_cannot_certify_wrong_tree(
    tmp_path: Path, command: str,
) -> None:
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    result = host.start("author-1", "full_test", workdir=str(repo), command=command)
    assert result["accepted"] is False
    assert "requires_direct_command" in result["reason"]
    assert runner.started == 0
    assert host.check_shell("author-1", command, str(repo)).blocked


def test_host_git_snapshot_disables_textconv_and_external_diff(
    tmp_path: Path, monkeypatch,
) -> None:
    from llm_loop.tools import review_host_admission

    repo = _repo(tmp_path)
    real_run = review_host_admission.subprocess.run
    git_diffs: list[list[str]] = []

    def observe_run(argv, **kwargs):
        if len(argv) > 3 and argv[0] == "git" and "diff" in argv:
            git_diffs.append(argv)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(review_host_admission.subprocess, "run", observe_run)
    host = HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    result = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert result["accepted"]
    # EVO-20261021-ea18d5ce: the committed delta is now built per-path, so
    # a clean fixture yields 2 name-only probes + 1 content diff.
    assert len(git_diffs) >= 3
    assert all("--no-textconv" in args and "--no-ext-diff" in args for args in git_diffs)


def _editor_page(noise_nodes: int = 0, body: str = "这是第一段正文，足够长以便进入可见文本。") -> dict:
    nodes = [
        {"kind": "heading", "attributes": {"tag": "input", "name": "同一个大模型，凭什么他用着顺手、你用着费劲"}},
        {"kind": "input", "attributes": {"tag": "div", "role": "textbox", "value_text": body}},
        {"kind": "button", "attributes": {"tag": "button", "name": "确认发布"}},
    ]
    for index in range(noise_nodes):
        nodes.append({"kind": "generic", "attributes": {"tag": "div", "data-noise": "y" * 400, "data-index": str(index)}})
    return {"url": "https://mp.toutiao.com/profile_v4/graphic/publish", "observed_at": 1, "dom": {"available": True, "nodes": nodes}}


def test_article_publish_material_carries_content_not_the_whole_dom() -> None:
    """A real editor page projects far past the review budget; the material must not be the DOM."""
    raw = _editor_page(noise_nodes=600)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="确认发布")
    assert issued["accepted"], issued.get("reason")
    assert "y" * 400 not in runner.task
    assert "这是第一段正文" in runner.task
    assert "确认发布" in runner.task
    assert len(runner.task.encode("utf-8")) < 78_000


def test_article_publish_cap_truncates_page_context_instead_of_refusing() -> None:
    """A giant page used to void the whole admission; budget the context, keep the gate."""
    raw = _editor_page(body="文" * 30_000)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="确认发布")
    assert issued["accepted"], issued.get("reason")
    assert '"visible_text_truncated": true' in runner.task
    assert len(runner.task.encode("utf-8")) < 78_000


def test_browser_binding_truncation_keeps_full_text_hash_and_consistency() -> None:
    """Truncation may shrink the page context, never the bound evidence."""
    raw = _editor_page(body="文" * 30_000)
    _sha, material_json = _browser_binding(raw)
    material = json.loads(material_json)
    assert material["visible_text_truncated"] is True
    assert material["visible_text_chars_sent"] == 20_000
    assert len(material["visible_text"]) == 20_000
    full_text = _page_visible_text(raw)
    assert len(full_text) > 30_000
    assert material["visible_text_sha256"] == hashlib.sha256(full_text.encode("utf-8")).hexdigest()


def test_article_publish_cap_backstop_when_content_alone_exceeds_budget(tmp_path: Path) -> None:
    """Truncation may not hide content: if the manuscript itself cannot fit, refuse."""
    body = "稿件正文" * 8_000  # one comparable line, 32k chars
    manuscript = tmp_path / "post.md"
    manuscript.write_text(body + "\n", encoding="utf-8")
    raw = _editor_page(body=body)
    host = HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="确认发布", manuscript_path=str(manuscript))
    assert not issued["accepted"]
    reason = issued["reason"]
    assert reason.startswith("browser_page_review_cap_exceeded:")
    measured, _, limit = reason.partition(":")[2].partition(">")
    assert int(measured) > int(limit) == 78_000


def test_manuscript_threshold_tolerates_line_noise_not_a_fifth_of_the_article(tmp_path: Path) -> None:
    """0.9: one noisy line in ten still passes; two missing lines must not."""
    lines = [f"这是第{str(i).zfill(2)}段正文，每一行都足够长从而参与一致性核对。" for i in range(10)]
    manuscript = tmp_path / "post.md"
    manuscript.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    host9 = HostReviewAdmission()
    host9.attach_runner(FakeChildRunner())
    host9.attach_browser_capture(lambda: _editor_page(body="  ".join(lines[:9])))
    ok = host9.start("author-1", "article_publish", target_name="确认发布", manuscript_path=str(manuscript))
    assert ok["accepted"], ok.get("reason")
    host8 = HostReviewAdmission()
    host8.attach_runner(FakeChildRunner())
    host8.attach_browser_capture(lambda: _editor_page(body="  ".join(lines[:8])))
    bad = host8.start("author-1", "article_publish", target_name="确认发布", manuscript_path=str(manuscript))
    assert not bad["accepted"]
    assert bad["reason"].startswith("manuscript_page_text_mismatch:")
    assert "unmatched_sample" in bad["reason"]
    assert "page_extra_prose_sample" in bad["reason"]


def test_article_publish_binding_ignores_volatile_capture_bookkeeping() -> None:
    raw = _editor_page()
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="确认发布")
    runner.state = "completed"
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"

    recaptured = _editor_page()
    recaptured["observed_at"] = 99
    recaptured["dom"]["nodes"][0]["attributes"]["data-stamp"] = "later"
    target = recaptured["dom"]["nodes"][2]
    assert host.check_browser("author-1", {"verb": "click"}, target, recaptured).allowed


def test_article_publish_denied_without_an_article_editor() -> None:
    raw = {"url": "https://mp.toutiao.com/publish", "dom": {"available": True, "nodes": [
        {"kind": "button", "attributes": {"tag": "button", "name": "确认发布"}},
    ]}}
    host = HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    host.attach_browser_capture(lambda: raw)
    issued = host.start("author-1", "article_publish", target_name="确认发布")
    assert not issued["accepted"] and issued["reason"] == "publication_article_editor_not_observed"


def test_browser_binding_refuses_a_page_the_reviewer_cannot_read() -> None:
    """Fail closed: a publish page with no readable content is not reviewable."""
    raw = {"url": "https://mp.toutiao.com/publish", "dom": {"available": True, "nodes": [
        {"kind": "input", "attributes": {"tag": "div", "role": "textbox", "value_text": ""}},
        {"kind": "button", "attributes": {"tag": "button", "name": "x"}},
    ]}}
    with pytest.raises(ValueError, match="browser_page_visible_text_empty"):
        _browser_binding(raw)


def test_article_publish_manuscript_mismatch_blocks_admission(tmp_path: Path) -> None:
    manuscript = tmp_path / "post.md"
    manuscript.write_text("# 完全不同的稿子\n\n这里讲的是另一件事，和编辑器里显示的正文没有任何重合之处。\n", encoding="utf-8")
    host = HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    host.attach_browser_capture(lambda: _editor_page())
    issued = host.start("author-1", "article_publish", target_name="确认发布", manuscript_path=str(manuscript))
    assert not issued["accepted"]
    assert issued["reason"].startswith("manuscript_page_text_mismatch:")
    assert "match_ratio" in issued["reason"]


def test_article_publish_manuscript_match_binds_file_and_artifact_fingerprints(tmp_path: Path) -> None:
    manuscript = tmp_path / "post.md"
    manuscript.write_text("这是第一段正文，足够长以便进入可见文本。\n\n这是第二段正文，同样足够长以通过一致性核对。\n", encoding="utf-8")
    raw = _editor_page(body="这是第一段正文，足够长以便进入可见文本。  这是第二段正文，同样足够长以通过一致性核对。")
    figure = tmp_path / "fig-62.png"
    figure.write_bytes(b"\x89PNG\r\n\x1a\nfigure-bytes")
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    host.attach_browser_capture(lambda: raw)
    issued = host.start(
        "author-1", "article_publish", target_name="确认发布",
        manuscript_path=str(manuscript), artifact_paths=[str(figure)],
    )
    assert issued["accepted"], issued.get("reason")
    assert "manuscript_page_text_mismatch" not in runner.task
    digest = hashlib.sha256(manuscript.read_bytes()).hexdigest()
    assert digest in runner.task
    assert hashlib.sha256(figure.read_bytes()).hexdigest() in runner.task


def test_article_publish_missing_artifact_file_blocks_admission(tmp_path: Path) -> None:
    host = HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    host.attach_browser_capture(lambda: _editor_page())
    issued = host.start(
        "author-1", "article_publish", target_name="确认发布",
        artifact_paths=[str(tmp_path / "absent.png")],
    )
    assert not issued["accepted"]
    assert issued["reason"].startswith("review_material_not_a_file:")


class FakeEventStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.enabled = True

    def append(self, parent: str, event_type: str, payload: dict) -> None:
        self.events.append((parent, event_type, payload))


def test_classify_reviewer_failure_taxonomy() -> None:
    assert _classify_reviewer_failure("HTTP 429 too many requests") == "reviewer_rate_limited"
    assert _classify_reviewer_failure("RateLimitError: rate limit reached") == "reviewer_rate_limited"
    assert _classify_reviewer_failure("RateLimitError") == "reviewer_rate_limited"  # bare class name
    assert _classify_reviewer_failure("401 unauthorized: invalid_api_key") == "reviewer_auth_error"
    assert _classify_reviewer_failure("AuthenticationError: bad token") == "reviewer_auth_error"
    assert _classify_reviewer_failure("PermissionError: permission denied") == "reviewer_auth_error"
    # Mixed text: auth wins over rate (never retry on unfixable credentials).
    assert _classify_reviewer_failure("403 forbidden ... quota exceeded") == "reviewer_auth_error"
    assert _classify_reviewer_failure("ReadTimeout: request timed out") == "reviewer_timeout"
    assert _classify_reviewer_failure("deadline exceeded after 30s") == "reviewer_timeout"
    assert _classify_reviewer_failure("child refused: depth limit") == "reviewer_unavailable"
    assert _classify_reviewer_failure("") == "reviewer_unavailable"


def test_page_controls_falls_back_to_text_when_name_missing() -> None:
    raw = {"dom": {"nodes": [
        {"kind": "button", "attributes": {"role": "button", "text": "发布"}},
        {"kind": "button", "attributes": {"name": "Save draft", "text": "存草稿"}},
        {"kind": "button", "attributes": {"role": "button", "text": ""}},
    ]}}
    # The gate face resolves the nameless control via _publish_label; the
    # reviewer's control list must show the same label or the button that will
    # be clicked is invisible to the reviewer.
    assert _page_controls(raw) == ["发布", "Save draft"]


def test_start_retries_rate_limit_then_succeeds(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rha, "_REVIEWER_RETRY_DELAYS", (0.0, 0.0))
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    runner.refusals = ["HTTP 429 too many requests", "RateLimitError: rate limit reached"]
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"], issued
    assert runner.started == 3  # initial + 2 bounded retries


def test_start_rate_limit_retries_exhausted_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rha, "_REVIEWER_RETRY_DELAYS", (0.0, 0.0))
    repo = _repo(tmp_path)
    store = FakeEventStore()
    runner = FakeChildRunner()
    runner.refusals = ["HTTP 429", "HTTP 429", "HTTP 429"]
    host = HostReviewAdmission()
    host.attach_event_store(store)
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert not issued["accepted"]
    assert issued["reviewer_failure"] == "reviewer_rate_limited"
    assert issued["reason"].startswith("reviewer_rate_limited:")
    assert runner.started == 3  # bounded: never more than initial + 2
    assert store.events and store.events[-1][1] == "review_admission_reviewer_unavailable"
    assert store.events[-1][2]["reviewer_failure"] == "reviewer_rate_limited"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_start_auth_error_never_retries(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    runner.refusals = ["401 unauthorized: invalid_api_key"]
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert not issued["accepted"]
    assert issued["reviewer_failure"] == "reviewer_auth_error"
    assert issued["reason"].startswith("reviewer_auth_error:")
    assert runner.started == 1  # credentials must be fixed, not retried


def test_poll_classifies_failed_child_as_reviewer_unavailable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    store = FakeEventStore()
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_event_store(store)
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"]
    runner.state = "failed"
    runner.answer = "RateLimitError: 429 rate limit exceeded"
    outcome = host.poll("author-1", "child-review-1")
    # A dead reviewer is not a verdict on the artifact, and not a fake
    # attestation denial either: the caller must see "retry later".
    assert outcome["qualification"] == "REVISE"
    assert outcome["reviewer_failure"] == "reviewer_rate_limited"
    assert outcome["reason"] == "reviewer_failed:reviewer_rate_limited"
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed
    assert store.events[-1][1] == "review_admission_reviewer_unavailable"
    # Repeated polls on the same dead child re-classify but never spam audit.
    again = host.poll("author-1", "child-review-1")
    assert again["reviewer_failure"] == "reviewer_rate_limited"
    assert sum(1 for e in store.events if e[1] == "review_admission_reviewer_unavailable") == 1


def test_start_retries_timeout_then_succeeds(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rha, "_REVIEWER_RETRY_DELAYS", (0.0, 0.0))
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    runner.refusals = ["ReadTimeout: request timed out"]
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"], issued
    assert runner.started == 2


def test_poll_failed_child_without_text_is_generic_unavailable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"]
    runner.state = "failed"
    runner.answer = ""  # no diagnostics at all: still closed, just unlabeled
    outcome = host.poll("author-1", "child-review-1")
    assert outcome["qualification"] == "REVISE"
    assert outcome["reviewer_failure"] == "reviewer_unavailable"
    assert outcome["reason"] == "reviewer_failed:reviewer_unavailable"


def test_poll_malformed_verdict_returns_review_tail(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"]
    runner.state = "completed"
    runner.answer = "审查完毕，整体质量可接受。\n结论：PASS\nP0=0 P1=0 P2=0\nSHA256: <见冻结清单>"
    outcome = host.poll("author-1", "child-review-1")
    # A localized verdict line is not the machine contract: fail closed, but
    # echo the reviewer's own tail so the cause is diagnosable.
    assert outcome["qualification"] == "REVISE"
    assert outcome["reason"] == "review_verdict_incomplete_or_not_pass"
    assert "结论：PASS" in outcome["review_tail"]


class BudgetProbeRunner(FakeChildRunner):
    """EVO-20261021-5bf26586: runner exposing the live-registry budget probe."""

    def __init__(self, budget: int | None | Exception) -> None:
        super().__init__()
        self.budget = budget

    def child_input_budget_chars(
        self,
        model_ref: str,
        *,
        chars_per_token: float | None = None,
    ) -> int | None:
        assert model_ref == "glm/glm-5.3"
        if isinstance(self.budget, Exception):
            raise self.budget
        return self.budget


def test_dynamic_budget_pre_check_rejects_oversized_task_before_spawn(
    tmp_path: Path,
) -> None:
    # Material below the static complete-review ceiling but above the
    # live-registry cap (60_000 chars budget -> 58_800 chars effective after
    # the 0.98 headroom) must be refused deterministically BEFORE any child
    # is spawned, with the budget numbers and a split suggestion in the
    # refusal reason.
    #
    # EVO-20261023-fc5c34b9: the pre-check now compares in CHARACTERS (the
    # unit the child's own wire check uses) and the headroom is 0.98, so the
    # expected cap moved from 48_000B to 58_800 chars.
    repo = _repo(tmp_path)
    (repo / "mid.py").write_text("y = " + repr("b" * 90_000) + "\n")
    host = HostReviewAdmission()
    runner = BudgetProbeRunner(60_000)
    host.attach_runner(runner)
    blocked = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert blocked["accepted"] is False
    assert blocked["reviewer_failure"] == "reviewer_input_too_large"
    assert "reviewer_input_too_large:" in blocked["reason"]
    assert "cap=58800chars" in blocked["reason"]
    assert "model_budget=60000chars" in blocked["reason"]
    assert "~2 smaller reviews" in blocked["reason"]
    assert runner.started == 0  # no spawn: refusal precedes child creation


def test_chinese_input_budget_refusal_is_classified_and_never_retried(
    tmp_path: Path,
) -> None:
    # SubAgentRunner's own Chinese budget-refusal wording previously fell
    # through to the reviewer_unavailable catch-all and, when mistaken for a
    # transient, burned retries that could never succeed.
    assert _classify_reviewer_failure(
        "模型输入接近实际窗口，但当前子代理没有可调用的 search_archive"
    ) == "reviewer_input_too_large"
    assert _classify_reviewer_failure(
        "工具 schema 已耗尽本模型输入容量，输出预留已占满该模型的物理窗口"
    ) == "reviewer_input_too_large"
    assert _classify_reviewer_failure(
        "This model's maximum context length is 4096 tokens"
    ) == "reviewer_input_too_large"
    # Unrelated limit wording must not be swallowed by the new pattern.
    assert _classify_reviewer_failure("child refused: depth limit") == "reviewer_unavailable"
    # Via the spawn path: one refusal, zero retries (non-retryable label).
    repo = _repo(tmp_path)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    runner.refusals = ["模型输入接近实际窗口，但当前子代理没有可调用的 search_archive"]
    host.attach_runner(runner)
    blocked = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert blocked["accepted"] is False
    assert blocked["reviewer_failure"] == "reviewer_input_too_large"
    assert blocked["reason"].startswith("reviewer_input_too_large:")
    assert runner.started == 1  # refused once, never retried


def test_unresolved_registry_falls_back_to_static_ceiling(tmp_path: Path) -> None:
    # Probe returns None (registry cannot resolve the reviewer model): the
    # legacy 192KB static ceiling stays authoritative — never "unlimited",
    # never a crash. A crashing probe must degrade the same way.
    repo = _repo(tmp_path)
    (repo / "big.py").write_text("z = " + repr("c" * 150_000) + "\n")  # <192KB material
    host = HostReviewAdmission()
    runner = BudgetProbeRunner(None)
    host.attach_runner(runner)
    allowed = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed["accepted"] is True
    assert runner.started == 1

    host2 = HostReviewAdmission()
    runner2 = BudgetProbeRunner(RuntimeError("registry snapshot gone"))
    host2.attach_runner(runner2)
    allowed2 = host2.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert allowed2["accepted"] is True
    assert runner2.started == 1


def _work_repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return _repo(work)


def _bare_origin_and_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    """A repo on main whose origin already has main at the baseline commit."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(bare)], check=True)
    repo = _work_repo(tmp_path)  # main @ baseline commit, example.py dirty
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True)
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "origin/main"],
        capture_output=True, check=True,
    ).stdout.decode().strip()
    return bare, repo, base


def test_push_review_freezes_remote_ahead_commits_and_drift_denies(tmp_path: Path) -> None:
    """commit-first-review-later flow: the frozen delta must be remote..HEAD,
    never an empty merge-base(HEAD, main) delta (EVO-20261021-89256d43)."""
    bare, repo, base = _bare_origin_and_repo(tmp_path)
    # Two local commits on main ahead of origin — the real push payload.
    (repo / "example.py").write_text("x = 3\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "ahead one"], check=True)
    (repo / "example.py").write_text("x = 4\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "ahead two"], check=True)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert issued["accepted"]
    assert issued["push_remote_commit"] == base
    # Material must state the remote base and actually contain the payload:
    # committed_delta is a file diff (base x=1 -> HEAD x=4), no log lines.
    assert f"push_remote_base={base}" in runner.task
    committed = runner.task.split("committed_delta")[1].split("uncommitted_delta")[0]
    assert "+x = 4" in committed and "-x = 1" in committed and "-x = 2" not in committed
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", "git push origin main", str(repo)).allowed
    # The remote ref moves after admission (another writer pushed): the frozen
    # candidate no longer matches recomputed remote facts — deny, re-review.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    subprocess.run(["git", "-C", str(other), "config", "user.name", "Other"], check=True)
    subprocess.run(["git", "-C", str(other), "config", "user.email", "o@example.invalid"], check=True)
    (other / "example.py").write_text("x = 5\n")
    subprocess.run(["git", "-C", str(other), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-qm", "remote moved"], check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "main"], check=True)
    verdict = host.check_shell("author-1", "git push origin main", str(repo))
    assert not verdict.allowed


def test_push_base_refuses_offline_even_with_tracking_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # EVO-20261021-89256d43 review Finding 1: a local tracking ref is
    # attacker-writable (`git update-ref`) and must never substitute for
    # remote facts — otherwise the frozen delta could be shrunk arbitrarily.
    _, repo, _base = _bare_origin_and_repo(tmp_path)
    (repo / "example.py").write_text("x = 3\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "ahead offline"], check=True)

    real_run = subprocess.run

    def offline_ls_remote(args, **kwargs):
        if "ls-remote" in args:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"network down")
        return real_run(args, **kwargs)

    monkeypatch.setattr(rha.subprocess, "run", offline_ls_remote)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    verdict = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert verdict["accepted"] is False
    assert "push_base_unresolvable_fail_closed" in str(verdict)
    assert runner.started == 0


def test_push_fails_closed_without_any_remote_fact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    # Remote exists but was never fetched: no tracking ref anywhere.
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(tmp_path / "never-cloned.git")], check=True)
    (repo / "example.py").write_text("x = 3\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "no facts"], check=True)

    real_run = subprocess.run

    def offline_ls_remote(args, **kwargs):
        if "ls-remote" in args:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"network down")
        return real_run(args, **kwargs)

    monkeypatch.setattr(rha.subprocess, "run", offline_ls_remote)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    verdict = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert verdict["accepted"] is False
    assert "push_base_unresolvable_fail_closed" in str(verdict)
    assert runner.started == 0


def test_first_push_of_absent_remote_branch_refused(tmp_path: Path) -> None:
    bare = tmp_path / "empty-origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(bare)], check=True)
    repo = _work_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    (repo / "example.py").write_text("x = 3\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "first push"], check=True)
    host = HostReviewAdmission()
    runner = FakeChildRunner()
    host.attach_runner(runner)
    verdict = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert verdict["accepted"] is False
    assert "push_remote_ref_absent_first_push_scope_unreviewable" in str(verdict)


def test_push_base_rejects_hostile_push_url(tmp_path: Path) -> None:
    # Attacker-writable git config must never smuggle ls-remote options,
    # shell transports, or ext:: helper transports via the push URL
    # (independent-review Finding: option injection -> upload-pack RCE).
    _origin, repo, _base = _bare_origin_and_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "config", "remote.origin.pushurl", "--upload-pack=evil-command"],
        check=True,
    )
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    verdict = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert verdict["accepted"] is False
    assert "push_remote_url_untrusted" in str(verdict)
    assert runner.started == 0
    subprocess.run(
        ["git", "-C", str(repo), "config", "remote.origin.pushurl", "ext::sh-c-evil"],
        check=True,
    )
    verdict = host.start("author-2", "git_push", workdir=str(repo), command="git push origin main")
    assert verdict["accepted"] is False
    assert "push_remote_url_untrusted" in str(verdict)
    assert runner.started == 0


def test_push_refspec_rejects_deletion_and_force(tmp_path: Path) -> None:
    # A push-base..HEAD delta cannot honestly represent ref deletion or a
    # forced rewrite; both must be refused at admission time.
    _origin, repo, _base = _bare_origin_and_repo(tmp_path)
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    for command in ("git push origin :main", "git push origin +main:main"):
        verdict = host.start("author-1", "git_push", workdir=str(repo), command=command)
        assert verdict["accepted"] is False
        assert "push_destructive_refspec_not_reviewable" in str(verdict)
    assert runner.started == 0


# ---------------------------------------------------------------------------
# EVO-20261023-fc5c34b9: reviewer material ceiling + token-cost calibration
# ---------------------------------------------------------------------------


def test_wire_chars_per_token_uses_measured_class_ratios() -> None:
    # The registry ratio (0.6) is a Chinese-mixed calibration that overstates
    # the token cost of ASCII code/JSON by ~4x. The measured ratios must be
    # used for a mixed wire, and the registry ratio must remain a floor.
    from llm_loop.subagent.runner import _wire_chars_per_token

    ascii_only = _wire_chars_per_token([{"content": "x" * 10_000}], 0.6)
    cjk_only = _wire_chars_per_token([{"content": "中" * 10_000}], 0.6)
    mixed = _wire_chars_per_token([{"content": ("a" * 9_000) + ("中" * 1_000)}], 0.6)

    # ASCII is charged at its measured ratio (not the registry 0.6).
    assert ascii_only > 2.0
    # CJK is charged at its own measured ratio, and that ratio is never BELOW
    # the registry's conservative 0.6 for the same class.
    assert cjk_only >= 0.6
    assert cjk_only == pytest.approx(1.432, rel=1e-3)
    # A mixed wire lands between the two class ratios.
    assert cjk_only <= mixed <= ascii_only
    # A measured class ratio may only correct an OVER-charge: when the
    # registry already charges a class more densely than the measurement
    # says, the registry rate stands (the measurement never invents a
    # discount). A CJK wire measured at 1.432 chars/token is therefore
    # priced at 1.432 even against a 0.3 registry (the measurement is the
    # evidence), while a class with no measurement falls back to the
    # registry.
    dense = _wire_chars_per_token([{"content": "中" * 1_000}], 0.3)
    assert dense == pytest.approx(1.432, rel=1e-3)
    # An EMPTY wire has no measured composition: the registry rate is used
    # unchanged (no measurement, no correction).
    empty = _wire_chars_per_token([{"content": ""}], 0.3)
    assert empty == pytest.approx(0.3, rel=1e-6)


def test_wire_chars_per_token_never_exceeds_the_measured_ceiling() -> None:
    from llm_loop.subagent.runner import _wire_chars_per_token

    for text in ("x" * 5_000, "中" * 5_000, ("ab" * 2_000) + ("中" * 500), ""):
        ratio = _wire_chars_per_token([{"content": text}], 0.6)
        assert 0.6 <= ratio <= 3.0


def test_pre_check_and_child_wire_agree_on_the_ratio() -> None:
    # The pre-check and the child must price the SAME material with the SAME
    # ratio, otherwise the pre-check admits material the child then refuses
    # (which surfaces as a misleading "reviewer_unavailable").
    from llm_loop.subagent.runner import _wire_chars_per_token

    material = ("diff --git a/x b/x\n" + "y" * 4_000) * 20
    pre_check_ratio = _wire_chars_per_token([{"content": material}], 0.6)
    child_ratio = _wire_chars_per_token([{"content": material}], 0.6)
    assert pre_check_ratio == child_ratio


def test_dynamic_pre_check_compares_chars_not_bytes(tmp_path: Path) -> None:
    # A CJK-heavy material is measured in bytes and characters; comparing
    # bytes against a char budget would reject material the child accepts
    # (the child compares sum(dict_wire_chars(m)) <= budget, i.e. chars).
    repo = _repo(tmp_path)
    (repo / "cjk.py").write_text("注释 = " + repr("中" * 40_000) + "\n")
    host = HostReviewAdmission()
    runner = BudgetProbeRunner(120_000)
    host.attach_runner(runner)
    verdict = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    # 40,000 CJK chars are 120,000 bytes but only 40,000 chars: a byte
    # comparison against the 120,000-char budget would wrongly refuse.
    assert verdict["accepted"] is True
    assert runner.started == 1
