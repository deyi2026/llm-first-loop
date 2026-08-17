#!/usr/bin/env python3
"""DeepSeek 用量账单成本报告（P4，2026-08-17）.

输入: 平台导出的 CSV（列: user_id,start_time_iso,end_time_iso,model,api_key_name,
      api_key,type,price,amount）。type ∈ {input_cache_hit_tokens,
      input_cache_miss_tokens, output_tokens, request_count}。
输出: 逐小时/渠道费用、缓存命中率、异常时段（miss 占比过高）告警。

用法:
  python scripts/usage_cost_report.py <bill.csv>
  python scripts/usage_cost_report.py <bill.csv> --hourly   # 逐小时明细
"""
import csv
import sys
from collections import defaultdict


def load_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def hour_key(start_iso: str) -> str:
    """2026-08-17T09:00:00+08:00 → 09:00"""
    try:
        return start_iso[11:16]
    except Exception:
        return start_iso[:16]


def build_report(rows: list[dict]) -> dict:
    per_hour = defaultdict(lambda: {"hit": 0, "miss": 0, "out": 0, "req": 0, "cost": 0.0, "key": ""})
    totals = {"hit": 0, "miss": 0, "out": 0, "req": 0, "cost": 0.0}
    for r in rows:
        typ = r.get("type", "")
        try:
            amt = int(float(r.get("amount") or 0))
        except ValueError:
            amt = 0
        try:
            price = float(r.get("price") or 0)
        except ValueError:
            price = 0.0
        hk = hour_key(r.get("start_time_iso", ""))
        key = r.get("api_key_name", "?")
        if typ == "request_count":
            per_hour[hk]["req"] += amt
            totals["req"] += amt
            continue
        if typ == "input_cache_hit_tokens":
            per_hour[hk]["hit"] += amt; totals["hit"] += amt
        elif typ == "input_cache_miss_tokens":
            per_hour[hk]["miss"] += amt; totals["miss"] += amt
        elif typ == "output_tokens":
            per_hour[hk]["out"] += amt; totals["out"] += amt
        cost = price * amt
        per_hour[hk]["cost"] += cost
        per_hour[hk]["key"] = key
        totals["cost"] += cost
    return {"per_hour": per_hour, "totals": totals}


def render(report: dict, hourly: bool = False) -> str:
    t = report["totals"]
    lines = []
    hit_rate = t["hit"] / (t["hit"] + t["miss"]) * 100 if (t["hit"] + t["miss"]) else 0.0
    lines.append(f"总请求 {t['req']} | 命中率 {hit_rate:.1f}% | 总费用 ${t['cost']:.2f}")
    lines.append(f"  构成: hit ${t['hit']*0.00000005:.2f} / miss ${t['miss']*0.0000015:.2f} / out ${t['out']*0.0000045:.2f} (参考单价)")
    if hourly:
        lines.append("")
        lines.append(f"{'时段':8s}{'请求':>5s}{'命中率':>8s}{'费用$':>9s}")
        for hk in sorted(report["per_hour"]):
            h = report["per_hour"][hk]
            hr = h["hit"] / (h["hit"] + h["miss"]) * 100 if (h["hit"] + h["miss"]) else 0.0
            flag = " ⚠️高miss" if (h["miss"] / (h["hit"] + h["miss"])) > 0.15 else ""
            lines.append(f"{hk:8s}{h['req']:5d}{hr:7.1f}%{h['cost']:9.2f}{flag}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    hourly = "--hourly" in sys.argv[1:]
    path = sys.argv[1] if sys.argv[1] != "--hourly" else sys.argv[2]
    rows = load_rows(path)
    report = build_report(rows)
    print(render(report, hourly=hourly))
    return 0


if __name__ == "__main__":
    sys.exit(main())
