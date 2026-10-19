#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 DPE 盲标复核包。

输入：S0 calls + S1 calls（已冻结）
实例集：v1.3 D ∪ v1.4 D
输出：
- dpe/review_pack.csv   给复核者（无 arm）
- dpe/review_pack.jsonl 机器可读（含 arm，评分用）
- dpe/key.json          blind_id -> (instance_id, arm)
- dpe/review_guide.md   复核说明

预填仅 P1/P4/P5（规则高置信），P2/P3 留空待人工。
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "s0_p28"))
sys.path.insert(0, str(ROOT))
import grade_v14 as G  # noqa: E402
import run_s0 as S  # noqa: E402

S0_CALLS = ROOT / "s0_p28" / "results" / "calls.jsonl"
S1_CALLS = ROOT / "s1_gold_filler" / "results" / "calls_s1.jsonl"
ARMS = ("no_card", "gold_card", "filler_card")

P1_RE = re.compile(
    r"(正文|内容|全文)[^。！？\n]{0,10}(没有|未|没)[^。！？\n]{0,8}(返回|拿到|读到|取回|带回)"
    r"|(读不到|看不到|拿不到|无法读取|无法获取|拿不到正文|取不到正文)")


def load():
    s0 = S.dedupe([json.loads(l) for l in S0_CALLS.read_text(encoding="utf-8").splitlines() if l.strip()])
    s1 = S.dedupe([json.loads(l) for l in S1_CALLS.read_text(encoding="utf-8").splitlines() if l.strip()])
    idx = {}
    for r in s0 + s1:
        if r.get("ok"):
            idx[(r["instance_id"], r["arm"])] = r
    return idx


def d_sets(idx):
    """v1.3 D 与 v1.4 D。"""
    ids = sorted({i for (i, _) in idx})
    g13 = S.GRADERS["v1.3"]
    d13 = []
    for i in ids:
        a, b = idx.get((i, "no_card")), idx.get((i, "orig_card"))
        if not a or not b:
            continue
        ca = all(v is True for v in g13(a["text"])[0].values())
        cb = all(v is True for v in g13(b["text"])[0].values())
        if (not ca) and cb:
            d13.append(i)
    d14 = [i for i in ids if idx.get((i, "no_card")) and idx.get((i, "orig_card"))
           and (not G.case_pass(G.grade(idx[(i, "no_card")]["text"])[0]))
           and G.case_pass(G.grade(idx[(i, "orig_card")]["text"])[0])]
    return sorted(set(d13) | set(d14)), d13, d14


def main() -> int:
    idx = load()
    inst_all, d13, d14 = d_sets(idx)
    # 分层抽样 20 个实例：重叠优先，再补两侧独有；固定 seed 可复现
    rng = random.Random(20261019)
    overlap = sorted(set(d13) & set(d14))
    only13 = sorted(set(d13) - set(d14))
    only14 = sorted(set(d14) - set(d13))
    rng.shuffle(overlap); rng.shuffle(only13); rng.shuffle(only14)
    take_overlap = overlap[:10]
    take13 = only13[:5]
    take14 = only14[:5]
    inst = sorted(set(take_overlap + take13 + take14))
    # 不足 20 时从剩余池补齐
    rest = [x for x in (overlap + only13 + only14) if x not in inst]
    inst = sorted(set(inst + rest[:max(0, 20 - len(inst))]))
    rows = []
    rng = random.Random(20261019)
    for i in inst:
        for arm in ARMS:
            r = idx.get((i, arm))
            if not r:
                continue
            rows.append({"instance_id": i, "arm": arm, "text": r["text"]})
    rng.shuffle(rows)
    key = {}
    out = []
    for n, r in enumerate(rows, 1):
        bid = "R%03d" % n
        key[bid] = {"instance_id": r["instance_id"], "arm": r["arm"],
                    "prompt_sha256": hashlib.sha256(r["text"].encode()).hexdigest()[:16]}
        t = r["text"]
        out.append({"blind_id": bid, "instance_id": r["instance_id"],
                    "P1_prefill": int(bool(P1_RE.search(t))),
                    "P4_prefill": int(G.check_c4(t)),
                    "P5_prefill": int(G.check_c2(t)),
                    "P1": "", "P2": "", "P3": "", "P4": "", "P5": "",
                    "note": "", "text": t})
    with (HERE / "review_pack.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["blind_id", "instance_id", "P1_prefill", "P4_prefill", "P5_prefill",
                                          "P1", "P2", "P3", "P4", "P5", "note", "text"])
        w.writeheader()
        w.writerows(out)
    with (HERE / "review_pack.jsonl").open("w", encoding="utf-8") as f:
        for r, o in zip(rows, out):
            f.write(json.dumps({**o, "arm": r["arm"]}, ensure_ascii=False) + "\n")
    (HERE / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "d_sets.json").write_text(json.dumps({"v1.3_D": sorted(d13), "v1.4_D": sorted(d14),
                                                   "union": sorted(inst_all)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"instances: v1.3 D={len(d13)} v1.4 D={len(d14)} union={len(inst_all)} sampled={len(inst)}")
    print(f"rows={len(out)}  -> dpe/review_pack.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
