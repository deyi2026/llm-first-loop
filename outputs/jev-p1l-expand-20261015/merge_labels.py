#!/usr/bin/env python3
"""双源盲评合并（DESIGN §11.3 冻结规则）：一致→dual_agreed；分歧→disputed；缺→missing。预运行闸 70%。"""
from __future__ import annotations
import json, pathlib, sys

DIR = pathlib.Path(__file__).resolve().parent
REPO = DIR.parents[1]
FIX = REPO / "tests" / "fixtures" / "jev" / "blind_eval_v2"
VALID = {"yes", "no", "unknown"}

def qids() -> list[str]:
    man = json.loads((FIX / "manifest.json").read_text())
    out = []
    for c in man["cases"]:
        cid = c["file"].split("/")[-1].removesuffix(".json")
        out += [f"{cid}/{q}" for q in c["questions"]]
    return out

def load(p: pathlib.Path) -> dict[str, str]:
    data = json.loads(p.read_text())
    assert isinstance(data, list), f"{p.name}: 顶层不是数组"
    m: dict[str, str] = {}
    for it in data:
        q, v = it.get("q"), it.get("value")
        if q not in ALL or v not in VALID:
            raise SystemExit(f"{p.name}: 非法条目 q={q!r} value={v!r}")
        if q in m:
            raise SystemExit(f"{p.name}: 重复条目 {q}")
        m[q] = v
    return m

ALL = qids()
assert len(ALL) == 44 and len(set(ALL)) == 44
A = load(DIR / "v2_labels_glm53flash.json")
B = load(DIR / "v2_labels_dsv4flash.json")
author = {e["q"]: e["value"] for e in json.loads((FIX / "labels" / "author_labels.json").read_text())["labels"]}

merged, agree_a = [], 0
stats = {"dual_agreed": 0, "disputed": 0, "missing": 0}
for q in ALL:
    a, b = A.get(q), B.get(q)
    if a is None or b is None:
        state, value = "missing", None
        stats["missing"] += 1
    elif a == b:
        state, value = "dual_agreed", a
        stats["dual_agreed"] += 1
    else:
        state, value = "disputed", None
        stats["disputed"] += 1
    if a is not None and a == author.get(q):
        agree_a += 1
    merged.append({"q": q, "glm53flash": a, "dsv4flash": b, "author": author.get(q),
                   "state": state, "value": value})

rate = stats["dual_agreed"] / len(ALL)
out = {
    "schema": "blind-eval-v2-dual/v1",
    "policy": "glm-5.3-flash 与 deepseek-v4-flash 取值一致→dual_agreed；不一致→disputed（不以作者标签仲裁）；任一缺→missing；预运行闸 dual_agreed/44≥70%",
    "stats": {**stats, "dual_agreement_rate": round(rate, 4),
              "author_vs_glm53flash_agreement": f"{agree_a}/44"},
    "labels": merged,
}
(DIR / "v2_labels_merged.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(out["stats"], ensure_ascii=False))
if rate < 0.70:
    print("label_insufficient: 双源一致率 <70%，§11.3 预运行闸触发，禁止评分")
    sys.exit(3)
