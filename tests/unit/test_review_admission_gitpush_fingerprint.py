"""EVO-20261107-3ebd74b6（人工批准 2026-11-08）红→绿：git_push 审查指纹绑定 commit 集.

push 的物理对象是 commit（push_head）：工作树改动与 untracked 文件不会随
push 上传，但现状 identity 把全文 material（含 working/untracked 段）+
untracked_shas 全量计入 sha——多会话共享主仓时，并行会话的正常落盘
（docs/*.md 设计稿等正当产物）让指纹在「审查签发→消费」窗口内漂移，
实测三连 PASS 后同轮消费 deny（2026-11-07 现场）。

红测试四类：
① 共享树并发写（untracked 新增 + tracked 工作树改动，均不随 push 上传）
  → PASS 资格不失效（同目标消费仍放行）；
② commit 集变化（新提交 / amend 重写 push_head）→ 仍 deny；
③ 审查者材料文本仍含 working/untracked 段（REVISE 判夹带权保留）；
④ full_test 的 identity 仍绑定树状态（它真实跑在树上，全量绑定正确，
  并发写后 sha 必变——锁定不随本演进放宽）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from llm_loop.tools.review_host_admission import HostReviewAdmission


class FakeChildRunner:
    def __init__(self) -> None:
        self.task = ""
        self.started = 0
        self.state = "running"
        self.answer = ""
        self.parent = "author-1"

    def start(self, task: str, **kwargs):
        self.started += 1
        self.task = task
        assert kwargs["required_tools"] == []
        assert kwargs["inherit"] is False
        assert kwargs["max_rounds"] == 1
        assert kwargs["review_isolated"] is True
        return {"accepted": True, "child_id": "child-review-1", "state": "running"}

    def review_terminal_current(self, child_id: str, parent_id: str):
        if self.state != "completed" or parent_id != self.parent:
            return None
        return {
            "child_id": child_id, "parent_id": parent_id, "state": self.state,
            "result_id": "result-verified", "generation": "gen-1",
            "review_isolated": True,
            "final_answer": self.answer,
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


def _mint_push_pass(repo: Path) -> tuple[HostReviewAdmission, dict]:
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo),
                        command="git push origin main")
    assert issued["accepted"], issued
    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"
    return host, issued


def test_concurrent_workspace_writes_do_not_invalidate_push_pass(tmp_path: Path) -> None:
    """① 并行会话正当落盘（untracked 设计稿 + tracked 工作树改动）→ 消费仍放行."""
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _commit(repo, "src_change.py", "value = 1\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    host, _ = _mint_push_pass(repo)
    # 模拟并行会话正当产物：新 untracked docs 笔记 + 已跟踪文件的本地未提交改动。
    # 两者都不会随 push 上传，不得使 PASS 失效。
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "design-draft.md").write_text("并行会话设计稿（正当工作区产物）\n")
    (repo / "src_change.py").write_text("value = 1  # 本地未提交修改\n")
    verdict = host.check_shell("author-1", "git push origin main", str(repo))
    assert verdict.allowed, (
        "共享树并发写（不随 push 上传的工作区产物）不应使 git_push PASS 失效："
        f"{verdict.reason}"
    )


def test_new_commit_after_pass_still_denies(tmp_path: Path) -> None:
    """② commit 集变化（新提交进入 push 目标）→ 仍 deny."""
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _commit(repo, "src_change.py", "value = 1\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    host, _ = _mint_push_pass(repo)
    _commit(repo, "src_change.py", "value = 2  # 未审查的新提交\n", "b3-unreviewed")
    assert not host.check_shell("author-1", "git push origin main", str(repo)).allowed


def test_amended_push_head_still_denies(tmp_path: Path) -> None:
    """② push_head 被 amend 重写（同信息不同内容）→ 仍 deny."""
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _commit(repo, "src_change.py", "value = 1\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    host, _ = _mint_push_pass(repo)
    (repo / "src_change.py").write_text("value = 42  # amend 注入未审查内容\n")
    subprocess.run(["git", "-C", str(repo), "add", "src_change.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--amend", "-m", "b2"], check=True)
    assert not host.check_shell("author-1", "git push origin main", str(repo)).allowed


def test_reviewer_material_still_shows_workspace_state(tmp_path: Path) -> None:
    """③ 审查者材料文本仍含 untracked/working 段（判夹带权保留，防静默收窄）."""
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _commit(repo, "src_change.py", "value = 1\n", "b2")
    _seed_bare_remote(repo, tmp_path, base)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "draft.md").write_text("草稿内容必须仍对审查者可见\n")
    (repo / "src_change.py").write_text("value = 1  # 本地未提交修改\n")
    runner = FakeChildRunner()
    host = HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo),
                        command="git push origin main")
    assert issued["accepted"], issued
    assert "draft.md" in runner.task and "草稿内容必须仍对审查者可见" in runner.task
    assert "本地未提交修改" in runner.task


def test_full_test_identity_still_binds_workspace_state(tmp_path: Path) -> None:
    """④ full_test 绑定不放宽：并发写后 sha 必变（它真实跑在树上）."""
    repo = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    _seed_bare_remote(repo, tmp_path, base)
    _commit(repo, "pending.py", "value = 1\n", "unpushed")  # 未推送 delta → 材料非空
    gate = HostReviewAdmission()
    cmd = "pytest -q"
    sha_before, _, _ = (
        gate._target("full_test", str(repo), cmd, "", None)[:3]
    )
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "concurrent.md").write_text("并行会话产物\n")
    sha_after, _, _ = (
        gate._target("full_test", str(repo), cmd, "", None)[:3]
    )
    assert sha_before != sha_after, "full_test 的 identity 必须继续绑定树状态"
