#!/usr/bin/env python3
"""EVO-20261106-7782d438：verify 凭证签发 CLI（append-only JSONL）。

干跑默认；--apply 才真正追加。凭证只对应真实 merge-review-gate PASS——
禁止预签/补签（见 skills/merge-review-gate/SKILL.md 合并执行纪律）。
幂等键 receipt_id = {lane_id}:{base_sha 前8}：同 lane+base 重验末行胜出；
base 前进后键变化，旧凭证经机检 d 判 verify_stale 强制重验。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm_loop.introspection.merge_queue import issue_verify_receipt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lane-id", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", default="")
    ap.add_argument("--scope", default="")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--ttl-s", type=int, default=86400)
    ap.add_argument("--receipts-path", default="data/audit/verify_receipts.jsonl")
    ap.add_argument("--apply", action="store_true", help="真正追加（默认干跑只打印）")
    ap.add_argument(
        "--carryover-from",
        default="",
        help="EVO-20261111-c273f61c：replay 型 rebase 降级重验。指向同 lane 原 base 的 pass 凭证 id",
    )
    ap.add_argument("--old-base", default="", help="carryover 用：rebase 前的 base sha")
    ap.add_argument("--old-head", default="", help="carryover 用：rebase 前的 lane head sha")
    ap.add_argument("--repo", default=".", help="carryover 用：git 仓路径（判据机检复跑）")
    args = ap.parse_args()

    carry = {
        "carryover_of": args.carryover_from,
        "repo_path": args.repo if args.carryover_from else "",
        "old_base": args.old_base,
        "old_head": args.old_head,
    }
    if args.carryover_from and (not args.old_base or not args.old_head):
        print("carryover 需要 --old-base/--old-head（fail-closed：判据必须机检复跑）", file=sys.stderr)
        return 2

    if args.apply:
        row = issue_verify_receipt(
            args.receipts_path,
            lane_id=args.lane_id,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            scope=args.scope,
            evidence=args.evidence,
            reviewer=args.reviewer,
            ttl_s=args.ttl_s,
            **carry,
        )
        print(f"ISSUED {row['receipt_id']} -> {args.receipts_path}")
        if row.get("carryover_of"):
            print(f"CARRYOVER of {row['carryover_of']} (EVO-20261111-c273f61c)")
        return 0
    print(
        "[dry-run] would append:",
        json.dumps(
            {
                "receipt_id": f"{args.lane_id}:{args.base_sha[:8]}",
                "lane_id": args.lane_id,
                "base_sha": args.base_sha,
                "result": "pass",
                "ttl_s": args.ttl_s,
            },
            ensure_ascii=False,
        ),
    )
    print(f"target: {args.receipts_path}（--apply 才写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
