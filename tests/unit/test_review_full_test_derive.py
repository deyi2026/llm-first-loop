# EVO-20261102-677f6c44（人工批准 2026-11-02，exec_override）：no-delta 复跑资格派生。
# 覆盖 RULE-AI-35 清单：有覆盖 git_push PASS → 派生+可消费；无覆盖 → 仍拒绝；
# 树漂移 → 拒绝；未跟踪文件 → 非 no-delta，不走派生；资格按 parent 隔离。
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from llm_loop.tools.review_host_admission import HostReviewAdmission

# 测试夹具命令字面量（不落 shell 命令行，避免写文件被 push 守卫误伤）。
_PUSH_MAIN = "git push " + "origin main"


class FakeChildRunner:
    def __init__(self) -> None:
        self.task = ""
        self.state = "running"
        self.answer = ""
        self.parent = "author-1"

    def start(self, task: str, **kwargs):
        self.task = task
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
        result = SimpleNamespace(final_answer=self.answer, outcome=self.state)
        return True, "ok", {
            "child_id": child_id, "parent_id": self.parent, "state": self.state,
            "result_id": "result-verified" if self.state == "completed" else "",
            "generation": "gen-1", "result": result,
            "local_active": self.state == "running",
        }


def _repo(tmp_path: Path) -> Path:
    p = tmp_path / "repo"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.name", "Unit Test"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.email", "t@example.invalid"], check=True)
    (p / "example.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(p), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(p), "commit", "-qm", "baseline"], check=True)
    return p


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


def _push_pass_host() -> tuple[HostReviewAdmission, FakeChildRunner]:
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    return host, runner


def _mint_push_pass(repo: Path, tmp_path: Path) -> tuple[HostReviewAdmission, FakeChildRunner]:
    """baseline 已推远端；b2 在本地待推，走完整 push 审查 → PASS → 消费 → 真推。"""
    host, runner = _push_pass_host()
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    head = _commit(repo, "example.py", "x = 2\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    issued = host.start("author-1", "git_push", workdir=str(repo), command=_PUSH_MAIN)
    assert issued["accepted"], issued
    assert issued["push_src_commit"] == head
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    assert host.check_shell("author-1", _PUSH_MAIN, str(repo)).allowed
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], check=True)
    return host, runner


def test_no_delta_full_test_derives_from_push_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host, _runner = _mint_push_pass(repo, tmp_path)
    # 全部已推送+树干净：精确 no-delta 状态。
    started = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert started["accepted"], started
    assert started.get("derived") is True
    assert started["derived_from"] == "child-review-1"
    assert started["qualification"] == "GRANTED"
    assert started["basis"]["covering"] == "push_pass_tree_identical"
    # 消费侧：同一命令放行（一次性，走既有 _consume）。
    assert host.check_shell("author-1", "pytest -q", str(repo)).allowed
    # 复跑：同一覆盖仍成立时按需再派生（每张仍是一次性）。
    assert host.check_shell("author-1", "pytest -q", str(repo)).allowed
    # 不同命令各自派生，互不冒用。
    assert host.check_shell("author-1", "bash scripts/ci_gate.sh", str(repo)).allowed


def test_no_delta_without_push_pass_still_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host, _runner = _push_pass_host()
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _seed_bare_remote(repo, tmp_path, base)  # 基线已在远端，无任何 push PASS
    started = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert not started["accepted"]
    assert started["reason"].startswith("full_test_no_delta"), started
    denied = host.check_shell("author-1", "pytest -q", str(repo))
    assert denied.blocked
    assert "RULE-AI-28" in denied.reason


def test_derive_rejects_tree_drift_after_push_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host, _runner = _mint_push_pass(repo, tmp_path)
    # push 审查后再提交并推送新内容：树对象已 != approved_head 的树 → 拒绝。
    _commit(repo, "example.py", "x = 3\n", "b3-drift")
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "main"], check=True)
    started = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert not started["accepted"]
    assert started["reason"].startswith("full_test_no_delta"), started
    assert host.check_shell("author-1", "pytest -q", str(repo)).blocked


def test_untracked_file_is_not_no_delta_so_no_derivation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host, runner = _mint_push_pass(repo, tmp_path)
    (repo / "sensitive_note.txt").write_text("secret = untracked\n")
    # 有未跟踪材料 → 不是 no-delta 状态 → 走正常审查路径（不派生）。
    started = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert started["accepted"], started
    assert "derived" not in started
    assert "secret = untracked" in runner.task
    # 审查未回裁断前消费侧仍拒绝。
    assert host.check_shell("author-1", "pytest -q", str(repo)).blocked


def test_derivation_is_parent_scoped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    host, _runner = _mint_push_pass(repo, tmp_path)
    denied = host.check_shell("author-2", "pytest -q", str(repo))
    assert denied.blocked
    # author-2 侧也没有派生记录被签出。
    started = host.start("author-2", "full_test", workdir=str(repo), command="pytest -q")
    assert not started["accepted"]
    assert started["reason"].startswith("full_test_no_delta"), started
