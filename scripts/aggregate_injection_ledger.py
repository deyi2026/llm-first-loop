#!/usr/bin/env python3
"""EVO-20260917-abdb3247 P0: injection ledger 聚合（只读，fail-open，不修改 ledger）."""
from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path

DEFAULT = Path("data/audit/injection_ledger.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(DEFAULT))
    ap.add_argument("--days", type=int, default=0, help="仅统计最近 N 天（0=全部）")
    args = ap.parse_args()
    p = Path(args.path)
    if not p.exists():
        print(f"ledger 不存在: {p}（尚无注入观测数据）")
        return 0
    by_kind: collections.Counter = collections.Counter()
    by_tool: collections.Counter = collections.Counter()
    by_source: collections.Counter = collections.Counter()
    by_day: collections.Counter = collections.Counter()
    by_pair: collections.Counter = collections.Counter()
    n = 0
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=args.days)).timestamp() if args.days else 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = float(r.get("ts", 0) or 0)
        if ts < cutoff:
            continue
        n += 1
        kind, tool = str(r.get("kind", "?")), str(r.get("tool", "-"))
        by_kind[kind] += 1
        by_tool[tool] += 1
        by_pair[(kind, tool)] += 1
        by_source[str(r.get("source", "-"))] += 1
        by_day[datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")] += 1
    print(f"rows={n} path={p}")
    for title, counter in (("kind", by_kind), ("tool", by_tool), ("source", by_source), ("day", by_day)):
        print(f"\n[{title}]")
        for key, v in counter.most_common():
            print(f"  {key}: {v}")
    print("\n[kind×tool]")
    for (kind, tool), v in by_pair.most_common():
        print(f"  {kind} × {tool}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
