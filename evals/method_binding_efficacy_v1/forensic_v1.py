#!/usr/bin/env python3
"""Provider-free post-hoc forensic on frozen matrix (exploratory, non-confirmatory).
Reads pool.json + matrix.jsonl + RESULT.json. Emits FORENSIC-DATA.json. No verdict reopening."""
import json, hashlib, re
from pathlib import Path
from collections import Counter
HERE = Path(__file__).resolve().parent
pool = json.loads((HERE/"pool.json").read_text())
rows = [json.loads(l) for l in (HERE/"matrix.jsonl").read_text().splitlines()]
formal = [r for r in rows if r["kind"]=="formal"]
latest = {}
for r in formal: latest[(r["case_id"], r["arm"])] = r
res = json.loads((HERE/"RESULT.json").read_text())
pc = {(p["case_id"], p["arm"]): p for p in res["per_case"]}

out = {"basis": {"matrix_sha256": res["matrix_sha256"], "result_sha256": hashlib.sha256((HERE/"RESULT.json").read_bytes()).hexdigest(),
                 "note": "post-hoc exploratory; frozen M1 verdict untouched"},
       "paired_transitions": {}, "mismatch_cases": []}
for kind in ("match","mismatch"):
    t = Counter()
    for cid in pool["run_order"]:
        c = pool["cases"][cid]
        if c["kind"] != kind: continue
        p0, p1 = pc[(cid,"C0")], pc[(cid,"C1")]
        t[(("C0错→C1对" if (not p0["correct"]) and p1["correct"] else
            "C0对→C1错" if p0["correct"] and (not p1["correct"]) else
            "双对" if p0["correct"] and p1["correct"] else "双错"))] += 1
    out["paired_transitions"][kind] = dict(t)

for cid in pool["run_order"]:
    c = pool["cases"][cid]
    if c["kind"] != "mismatch": continue
    p0, p1 = pc[(cid,"C0")], pc[(cid,"C1")]
    card_name = re.search(r"name:\s*(\S+)", c["card"]).group(1)
    entry = {"case_id": cid, "trap_card": card_name, "trigger_source_method": c["trigger_source"],
             "expected": c["expected"], "trigger": c["trigger"][:400],
             "pairs": {"C0": {"verdict": p0["verdict"], "correct": p0["correct"], "answer": latest[(cid,"C0")]["final_answer"]},
                       "C1": {"verdict": p1["verdict"], "correct": p1["correct"], "answer": latest[(cid,"C1")]["final_answer"]}},
             "transition": ("双对" if p0["correct"] and p1["correct"] else "双错" if not p0["correct"] and not p1["correct"]
                            else "C0错→C1对" if p1["correct"] else "C0对→C1错")}
    out["mismatch_cases"].append(entry)
(HERE/"FORENSIC-DATA.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("paired:", json.dumps(out["paired_transitions"], ensure_ascii=False))
print("C1-wrong:", [e["case_id"] for e in out["mismatch_cases"] if not e["pairs"]["C1"]["correct"]])
print("FORENSIC-DATA.json written, sha256 =", hashlib.sha256((HERE/"FORENSIC-DATA.json").read_bytes()).hexdigest()[:16])
