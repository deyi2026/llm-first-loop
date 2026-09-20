#!/usr/bin/env python3
"""Worktree 生命周期治理工具（EVO-20260920-47e815f1）.

三档机制合一：
  audit       A/B/C 吸收度分类（A=HEAD∈main；B=补丁全等价 git cherry 全'-'；C=有+提交），
              --delete-ab 机械回收 A/B（仅 dirty=0，dirty>0 跳过并标注 SKIP_DIRTY）。
  register    临时路径 worktree 登记 TTL sidecar（默认 72h，data/state/worktree_ttl.jsonl）。
  triage      超期 triage：先 rescue 分支保底（C/detach），再注销 worktree；
              --prune 清理已不存在条目；dirty>0 只报 REQUIRES_MANUAL 不强删。
  merge-hint  PR 合并后等价落地提示：列出补丁已全在 main 的本地分支（等时副本源头阻断）。

零 LLM/零网络；只依赖本地 git。测试：tests/scripts/test_worktree_lifecycle.py。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TTL_HOURS = 72.0


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc


def _repo_root(cli_repo: str | None) -> Path:
    if cli_repo:
        return Path(cli_repo).resolve()
    proc = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip())


def _worktrees(repo: Path) -> list[dict[str, str]]:
    """porcelain 输出 → [{path, head, branch?}]（含主仓首条）."""
    out = _git(repo, "worktree", "list", "--porcelain").stdout
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": val}
        elif key in ("HEAD", "branch"):
            cur[key] = val
    if cur:
        entries.append(cur)
    return entries


def _dirty_count(wt: Path) -> int:
    proc = _git(wt, "status", "--porcelain")
    return len([ln for ln in proc.stdout.splitlines() if ln.strip()])


def _cherry_plus(repo: Path, ref: str) -> int:
    out = _git(repo, "cherry", "main", ref).stdout
    return len([ln for ln in out.splitlines() if ln.startswith("+")])


def classify(repo: Path, wt: dict[str, str]) -> dict[str, object]:
    """单个 worktree → 分类记录."""
    path = Path(wt["path"])
    head = wt.get("HEAD", "")
    branch_ref = wt.get("branch", "")
    branch = branch_ref.replace("refs/heads/", "") if branch_ref else ""
    head_in_main = (
        _git(repo, "merge-base", "--is-ancestor", head, "main", check=False).returncode == 0
    )
    if head_in_main:
        cls = "A"
        plus = 0
    else:
        plus = _cherry_plus(repo, head)
        cls = "B" if plus == 0 else "C"
    return {
        "class": cls,
        "dirty": _dirty_count(path),
        "branch": branch or f"DETACH:{head[:9]}",
        "path": str(path),
        "plus": plus,
    }


def _checked_out_branches(repo: Path) -> set[str]:
    return {
        wt.get("branch", "").replace("refs/heads/", "")
        for wt in _worktrees(repo)
        if wt.get("branch")
    }


def cmd_audit(repo: Path, delete_ab: bool) -> int:
    rows = [classify(repo, wt) for wt in _worktrees(repo) if Path(wt["path"]) != repo]
    removed, skipped = [], []
    if delete_ab:
        for r in rows:
            if r["class"] not in ("A", "B"):
                continue
            if r["dirty"] > 0:
                skipped.append((r, "SKIP_DIRTY"))
                continue
            proc = _git(repo, "worktree", "remove", str(r["path"]), check=False)
            if proc.returncode != 0:
                skipped.append((r, "REMOVE_FAIL"))
                continue
            branch = r["branch"]
            # 删除后重算在岗集合：被删 worktree 自身占用的分支已释放
            busy_now = _checked_out_branches(repo)
            if (
                branch
                and not branch.startswith("DETACH:")
                and branch not in busy_now
                and branch != "main"
            ):
                _git(repo, "branch", "-D", branch, check=False)
            removed.append(r)
    for r in rows:
        print(f"{r['class']}\t{r['dirty']}\t{r['branch']}\t{r['path']}")
    for r, why in skipped:
        print(f"#{why}\t{r['path']}", file=sys.stderr)
    n = {"A": 0, "B": 0, "C": 0}
    for r in rows:
        n[str(r["class"])] = n.get(str(r["class"]), 0) + 1
    print(
        f"#summary A={n.get('A', 0)} B={n.get('B', 0)} C={n.get('C', 0)}"
        f" removed={len(removed)} skipped={len(skipped)}"
    )
    return 0


# ── TTL sidecar ──


@dataclass
class TtlEntry:
    path: str
    branch: str
    head: str
    ttl_hours: float
    registered_at: float
    note: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, sort_keys=True)


def _sidecar(repo: Path) -> Path:
    return repo / "data" / "state" / "worktree_ttl.jsonl"


def _load_sidecar(repo: Path) -> list[TtlEntry]:
    f = _sidecar(repo)
    if not f.exists():
        return []
    entries: list[TtlEntry] = []
    for line in f.read_text().splitlines():
        if line.strip():
            entries.append(TtlEntry(**json.loads(line)))
    return entries


def _save_sidecar(repo: Path, entries: list[TtlEntry]) -> None:
    f = _sidecar(repo)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(e.to_json() + "\n" for e in entries))


def cmd_register(repo: Path, wt_path: str, ttl_hours: float, note: str) -> int:
    path = str(Path(wt_path).resolve())
    matches = [wt for wt in _worktrees(repo) if wt["path"] == path]
    if not matches:
        print(f"ERROR: 非 worktree 路径: {path}", file=sys.stderr)
        return 2
    wt = matches[0]
    branch = wt.get("branch", "").replace("refs/heads/", "")
    entry = TtlEntry(
        path=path,
        branch=branch,
        head=wt.get("HEAD", ""),
        ttl_hours=ttl_hours,
        registered_at=time.time(),
        note=note,
    )
    entries = [e for e in _load_sidecar(repo) if e.path != path]
    entries.append(entry)
    _save_sidecar(repo, entries)
    print(f"registered\t{path}\tttl={ttl_hours}h")
    return 0


def _rescue_branch_name(repo: Path, base: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    name = f"rescue/{Path(base).name}-{stamp}"
    suffix = 2
    while _git(repo, "rev-parse", "--verify", name, check=False).returncode == 0:
        name = f"rescue/{Path(base).name}-{stamp}-{suffix}"
        suffix += 1
    return name


def cmd_triage(repo: Path, prune: bool, expire_delete: bool) -> int:
    entries = _load_sidecar(repo)
    if not entries:
        print("#summary expired=0 pruned=0 rescued=0 removed=0 manual=0")
        return 0
    live_paths = {wt["path"] for wt in _worktrees(repo)}
    kept: list[TtlEntry] = []
    expired: list[tuple[TtlEntry, str]] = []
    pruned = 0
    for e in entries:
        if e.path not in live_paths:
            pruned += 1
            continue
        if time.time() - e.registered_at > e.ttl_hours * 3600:
            expired.append((e, classify(repo, {"path": e.path, "HEAD": e.head, "branch": ""})))
        else:
            kept.append(e)
    rescued = removed = manual = 0
    if expire_delete:
        still_keep: list[TtlEntry] = list(kept)
        for e, info in expired:
            if int(info["dirty"]) > 0:
                manual += 1
                still_keep.append(e)
                print(f"REQUIRES_MANUAL\t{e.path}\tdirty={info['dirty']}", file=sys.stderr)
                continue
            branch = e.branch or _rescue_branch_name(repo, e.path)
            if info["class"] == "C" and not e.branch:
                _git(repo, "branch", branch, e.head)
                rescued += 1
            elif info["class"] == "C":
                branch = e.branch  # 已有分支即保底
            proc = _git(repo, "worktree", "remove", e.path, check=False)
            if proc.returncode != 0:
                manual += 1
                still_keep.append(e)
                print(f"REQUIRES_MANUAL\t{e.path}\tremove_fail", file=sys.stderr)
                continue
            removed += 1
            print(f"expired-removed\t{e.path}\trescue={branch if info['class'] == 'C' else '-'}")
        kept = still_keep
    else:
        for e, info in expired:
            print(f"expired\t{e.path}\tclass={info['class']}\tdirty={info['dirty']}")
    _save_sidecar(repo, kept)
    print(
        f"#summary expired={len(expired)} pruned={pruned} rescued={rescued}"
        f" removed={removed} manual={manual}"
    )
    return 0


def cmd_merge_hint(repo: Path, branches: list[str], delete: bool) -> int:
    if not branches:
        busy = _checked_out_branches(repo)
        out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
        branches = [b for b in out.splitlines() if b and b != "main" and b not in busy]
    deletable = [b for b in branches if _cherry_plus(repo, b) == 0]
    for b in sorted(deletable):
        print(f"deletable\t{b}")
    for b in sorted(set(branches) - set(deletable)):
        print(f"has-unmerged\t{b}")
    if delete and deletable:
        busy = _checked_out_branches(repo)
        for b in deletable:
            if b not in busy:
                _git(repo, "branch", "-D", b)
    print(f"#summary deletable={len(deletable)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--repo", help="仓库根（默认 cwd 的 toplevel）")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("audit", help="A/B/C 吸收度分类")
    pa.add_argument("--delete-ab", action="store_true", help="删除 A/B 类（dirty=0）")
    pr = sub.add_parser("register", help="登记 TTL")
    pr.add_argument("worktree")
    pr.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    pr.add_argument("--note", default="")
    pt = sub.add_parser("triage", help="超期 triage")
    pt.add_argument("--prune", action="store_true", help="清理已注销条目")
    pt.add_argument("--expire-delete", action="store_true", help="超期项 rescue 后注销")
    pm = sub.add_parser("merge-hint", help="合并后等价分支提示")
    pm.add_argument("branches", nargs="*")
    pm.add_argument("--delete", action="store_true", help="执行删除")
    args = p.parse_args(argv)
    repo = _repo_root(args.repo)
    if args.cmd == "audit":
        return cmd_audit(repo, args.delete_ab)
    if args.cmd == "register":
        return cmd_register(repo, args.worktree, args.ttl_hours, args.note)
    if args.cmd == "triage":
        return cmd_triage(repo, args.prune, args.expire_delete)
    return cmd_merge_hint(repo, args.branches, args.delete)


if __name__ == "__main__":
    sys.exit(main())
