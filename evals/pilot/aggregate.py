#!/usr/bin/env python3
"""pilot 汇总：每 (agent, task) 取按行序最新 K=3 条（t11 修正 prompt 后重跑覆盖旧失败记录）。

产出：stdout markdown 表 + 时长中位数对比。
"""
from __future__ import annotations
import json, statistics, sys
from pathlib import Path

K = 3
rows = [json.loads(l) for l in Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/agentpilot/results.jsonl").read_text().splitlines() if l.strip()]

# 每 (agent,task) 保留最新 K 条（按文件行序=完成时间序）
latest: dict[tuple, list] = {}
for r in rows:
    latest.setdefault((r["agent"], r["task"]), []).append(r)
for k in latest:
    latest[k] = latest[k][-K:]

tasks = sorted({t for _, t in latest})
agents = sorted({a for a, _ in latest})

print("| task | " + " | ".join(f"{a} pass" for a in agents) + " | " + " | ".join(f"{a} 中位时长s" for a in agents) + " |")
print("|---" * (1 + 2 * len(agents)) + "|")
for t in tasks:
    ps, ds = [], []
    for a in agents:
        rs = latest.get((a, t), [])
        ps.append(f"{sum(r['pass'] for r in rs)}/{len(rs)}" if rs else "-")
        ds.append(f"{statistics.median(r['dur'] for r in rs):.0f}" if rs else "-")
    print(f"| {t} | " + " | ".join(ps) + " | " + " | ".join(ds) + " |")

print()
fails = []
for (a, t), rs in sorted(latest.items()):
    for r in rs:
        if not r["pass"]:
            fails.append((a, t, r["run"], r.get("verify_err", "")[:200]))
print("## 失败明细（最新 K 口径内）")
for f in fails:
    print(f"- {f[0]} {f[1]} r{f[2]}: {f[3]}")
if not fails:
    print("-（无）")

print()
for a in agents:
    rs = [r for (ag, _), v in latest.items() if ag == a for r in v]
    print(f"**{a}**: {sum(r['pass'] for r in rs)}/{len(rs)} = {sum(r['pass'] for r in rs)/len(rs):.0%}，时长中位 {statistics.median(r['dur'] for r in rs):.0f}s（n={len(rs)}）")
