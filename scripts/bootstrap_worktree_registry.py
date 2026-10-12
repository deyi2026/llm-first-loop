#!/usr/bin/env python3
"""T0-A1/A2: worktree registry bootstrap + 嵌套创建 guard（CLI）.

用法:
  bootstrap（全量落表，默认 protected=runtime_manifest 现役 code root）:
    python3 scripts/bootstrap_worktree_registry.py --runtime-root <mirror>
  显式 protected / 回滚候选:
    ... --protected <path> [--protected <path>] --rollback <path>
  创建前嵌套检查（官方创建路径；拒绝 rc=2）:
    ... --check-add <target-path>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_loop.runtime.worktree_registry import (  # noqa: E402
    bootstrap,
    check_add_target,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime-root", default=".", help="runtime root（默认 cwd）")
    ap.add_argument("--repo", default=None, help="git repo（默认 runtime-root）")
    ap.add_argument("--protected", action="append", default=None, help="显式 protected 路径（可重复）")
    ap.add_argument("--rollback", action="append", default=None, help="回滚候选（可重复）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-add", default=None, help="拟创建 worktree 路径（嵌套检查，拒绝 rc=2）")
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).resolve()
    repo = Path(args.repo).resolve() if args.repo else runtime_root

    if args.check_add:
        ok, reason = check_add_target(repo, Path(args.check_add), runtime_root)
        print(reason)
        return 0 if ok else 2

    reg = bootstrap(
        runtime_root,
        repo,
        protected_paths=args.protected,
        rollback_candidates=args.rollback,
        dry_run=args.dry_run,
    )
    print(f"registry: total={reg['counts']['total']} protected={reg['counts']['protected']} "
          f"legacy={reg['counts']['legacy']} retired={reg['counts']['retired']} "
          f"nested_pairs={reg['counts']['nested_pairs']}")
    if reg.get("nested"):
        print("NESTED-DETECTED:")
        for pair in reg["nested"]:
            print(f"  outer={pair['outer']} inner={pair['inner']}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
