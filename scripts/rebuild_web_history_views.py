#!/usr/bin/env python3
"""Explicit bounded maintenance of derived Web history views; never rewrite history.

Use the same sessions and identity roots as the running SessionStore. Select at
most eight known session IDs. Without --apply, print the plan only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_loop.core.session import SessionStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", type=Path, required=True)
    parser.add_argument("--identity-root", type=Path, required=True)
    parser.add_argument("--max-source-mib", type=int, default=64, choices=range(1, 129), metavar="1..128")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("session_ids", nargs="+")
    args = parser.parse_args()
    if len(args.session_ids) > 8:
        parser.error("select at most eight session IDs")
    if not args.sessions_dir.is_dir() or not args.identity_root.is_dir():
        parser.error("both existing roots are required")
    budget = args.max_source_mib * 1024 * 1024
    if not args.apply:
        print(json.dumps({"status": "plan_only", "session_ids": args.session_ids, "max_source_bytes": budget}))
        return 0
    store = SessionStore(args.sessions_dir, identity_root=args.identity_root)
    results = store.rebuild_history_views_batch(args.session_ids, max_source_bytes=budget)
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(row["status"] in {"rebuilt", "metadata_only"} for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
