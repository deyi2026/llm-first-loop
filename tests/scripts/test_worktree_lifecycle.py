"""EVO-20260920-47e815f1 worktree 生命周期治理测试（零 LLM 零网络）.

覆盖: audit A/B/C 分类 / --delete-ab 回收与 SKIP_DIRTY 保护 / TTL register+triage
（rescue 保底、REQUIRES_MANUAL、--prune）/ merge-hint 等价分支删除与在岗保护。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "worktree_lifecycle.py"


def _run(
    *args: str, cwd: Path | None = None, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = {**os.environ, **env} if env else None
    proc = subprocess.run(
        list(args), capture_output=True, text=True, cwd=cwd, check=False, env=run_env
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"{' '.join(args)} 失败: {proc.stderr}")
    return proc


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return _run("git", "-C", str(repo), *args, env=env).stdout


def _commit(wt: Path, fname: str, content: str, when: str = "2001-01-01T00:00:00 +0000") -> str:
    fixed = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    (wt / fname).write_text(content)
    _run("git", "-C", str(wt), "add", fname)
    _run("git", "-C", str(wt), "commit", "-m", f"add {fname}", env=fixed)
    return _git(wt, "rev-parse", "HEAD").strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-b", "main", str(repo))
    _run("git", "-C", str(repo), "config", "user.email", "t@t.local")
    _run("git", "-C", str(repo), "config", "user.name", "t")
    _commit(repo, "base.txt", "base\n")
    return repo


def _setup_abc(repo: Path) -> dict[str, str]:
    """a: head∈main（A）；b: 补丁等价（B）；c: 有+提交（C）."""
    wta = repo / "wt-a"
    _run("git", "-C", str(repo), "worktree", "add", "-b", "br-a", str(wta))
    head_a = _commit(wta, "a.txt", "a\n")
    _git(repo, "merge", "--ff-only", head_a)  # main 吸收 a → A 类

    wtb = repo / "wt-b"
    _run("git", "-C", str(repo), "worktree", "add", "-b", "br-b", str(wtb))
    _commit(wtb, "b.txt", "b\n")  # 固定 2001 日期（committer 日期决定 SHA）
    b_sha = _git(wtb, "rev-parse", "HEAD").strip()
    # cherry-pick 的 committer 日期=now(≠2001) → 确定性得到不同 SHA、相同 patch-id
    _git(repo, "cherry-pick", b_sha)  # main 等价落地 b 补丁 → B 类
    assert _git(repo, "rev-parse", "main").strip() != b_sha  # fixture 防退化

    wtc = repo / "wt-c"
    _run("git", "-C", str(repo), "worktree", "add", "-b", "br-c", str(wtc))
    _commit(wtc, "c.txt", "c\n")  # 未合并 → C 类
    return {"a": head_a, "b": b_sha}


def _lifecycle(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(sys.executable, str(SCRIPT), "--repo", str(repo), *args)


def _audit_classes(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if line.startswith("#"):
            continue
        cls, _dirty, branch, _path = line.split("\t")
        out[branch] = cls
    return out


def test_audit_classification_abc(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _setup_abc(repo)
    proc = _lifecycle(repo, "audit")
    classes = _audit_classes(proc.stdout)
    assert classes["br-a"] == "A"
    assert classes["br-b"] == "B"
    assert classes["br-c"] == "C"
    assert "A=1 B=1 C=1" in proc.stdout


def test_audit_delete_ab_keeps_c(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _setup_abc(repo)
    proc = _lifecycle(repo, "audit", "--delete-ab")
    assert "removed=2 skipped=0" in proc.stdout
    remaining = _git(repo, "worktree", "list", "--porcelain")
    assert "wt-a" not in remaining and "wt-b" not in remaining
    assert "wt-c" in remaining
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert "br-a" not in branches and "br-b" not in branches
    assert "br-c" in branches and "main" in branches


def test_audit_delete_ab_skips_dirty(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _setup_abc(repo)
    (repo / "wt-a" / "dirty.txt").write_text("x")  # A 类但 dirty
    proc = _lifecycle(repo, "audit", "--delete-ab")
    assert "removed=1 skipped=1" in proc.stdout
    assert "SKIP_DIRTY" in proc.stderr
    assert (repo / "wt-a").exists()  # 不强删
    assert "br-a" in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")


def test_register_and_triage_expire_with_rescue(tmp_path: Path):
    repo = _make_repo(tmp_path)
    wtd = repo / "wt-d"
    _run("git", "-C", str(repo), "worktree", "add", "--detach", str(wtd))
    head = _commit(wtd, "d.txt", "d\n")  # detach 上独立提交 → C
    _lifecycle(repo, "register", str(wtd), "--ttl-hours", "0", "--note", "test")
    sidecar = repo / "data" / "state" / "worktree_ttl.jsonl"
    entry = json.loads(sidecar.read_text().strip())
    assert entry["head"] == head
    proc = _lifecycle(repo, "triage", "--expire-delete")
    assert "expired-removed" in proc.stdout
    assert "wt-d" not in _git(repo, "worktree", "list", "--porcelain")
    rescue_branches = [
        ln
        for ln in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()
        if ln.startswith("rescue/")
    ]
    assert len(rescue_branches) == 1
    assert _git(repo, "rev-parse", rescue_branches[0]).strip() == head
    assert sidecar.read_text() == ""  # 条目已清


def test_triage_dirty_requires_manual(tmp_path: Path):
    repo = _make_repo(tmp_path)
    wtd = repo / "wt-d"
    _run("git", "-C", str(repo), "worktree", "add", "--detach", str(wtd))
    _commit(wtd, "d.txt", "d\n")
    (wtd / "uncommitted.txt").write_text("x")
    _lifecycle(repo, "register", str(wtd), "--ttl-hours", "0")
    proc = _lifecycle(repo, "triage", "--expire-delete")
    assert "REQUIRES_MANUAL" in proc.stderr
    assert "manual=1" in proc.stdout
    assert wtd.exists()  # 不强删
    assert (repo / "data" / "state" / "worktree_ttl.jsonl").read_text() != ""


def test_triage_prune_gone_entries(tmp_path: Path):
    repo = _make_repo(tmp_path)
    wtd = repo / "wt-d"
    _run("git", "-C", str(repo), "worktree", "add", "--detach", str(wtd))
    _lifecycle(repo, "register", str(wtd), "--ttl-hours", "999")
    _run("git", "-C", str(repo), "worktree", "remove", str(wtd))
    proc = _lifecycle(repo, "triage", "--prune")
    assert "pruned=1" in proc.stdout
    assert (repo / "data" / "state" / "worktree_ttl.jsonl").read_text() == ""


def test_merge_hint_deletes_equivalent_only(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _setup_abc(repo)
    _run("git", "-C", str(repo), "worktree", "remove", str(repo / "wt-a"))
    _run("git", "-C", str(repo), "worktree", "remove", str(repo / "wt-b"))
    proc = _lifecycle(repo, "merge-hint", "--delete")
    assert "deletable\tbr-a" in proc.stdout and "deletable\tbr-b" in proc.stdout
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert "br-a" not in branches and "br-b" not in branches
    assert "br-c" in branches
