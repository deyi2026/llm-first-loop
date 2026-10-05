#!/usr/bin/env python3
"""Deterministic provider-free analyzer. Only runs after matrix complete. Frozen formulas."""
import hashlib, json, sys
from pathlib import Path
from collections import defaultdict
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from protocol import SPEC_SHA256, parse_verdict, one_sided_z_test

pool = json.loads((HERE / "pool.json").read_text())
rows = [json.loads(l) for l in (HERE / "matrix.jsonl").read_text().splitlines()]
formal = [r for r in rows if r["kind"] == "formal"]
latest = {}
for r in formal:  # later row wins (rerun replaces original)
    key = (r["case_id"], r["arm"]); latest[key] = r
cells = {k: r for k, r in latest.items()}
N = len(pool["run_order"]); assert len(cells) == 2 * N, f"expected {2*N} cells, got {len(cells)}"

def healthy(r): return r.get("status") == "RUN_OK" and not r.get("truncated") and not r.get("fallback_used") and r.get("model_used") == "deepseek/v4flash-canonical-guard" or r.get("model_canonical_ok") is True
acc = {a: defaultdict(lambda: [0, 0]) for a in ("C0", "C1")}  # stratum -> [correct, total]
g1 = {a: [0, 0] for a in ("C0", "C1")}                        # [apply+record_use, expected-apply total]
tok = {a: [] for a in ("C0", "C1")}; wall = {a: [] for a in ("C0", "C1")}
other = {a: 0 for a in ("C0", "C1")}; tech_orig = {a: 0 for a in ("C0", "C1")}
per_case = []
for cid in pool["run_order"]:
    case = pool["cases"][cid]
    for a in ("C0", "C1"):
        r = cells[(cid, a)]
        v = parse_verdict(r.get("final_answer", "")) if healthy(r) else "OTHER"
        correct = (v == case["expected"])
        acc[a][case["kind"]][1] += 1; acc[a]["all"][1] += 1
        if correct: acc[a][case["kind"]][0] += 1; acc[a]["all"][0] += 1
        if v == "OTHER": other[a] += 1
        if case["expected"] == "APPLY":
            g1[a][1] += 1
            if v == "APPLY" and r.get("record_use_applied"): g1[a][0] += 1
        if healthy(r):
            tok[a].append(r["tokens_in"] + r["tokens_out"]); wall[a].append(r["wall_s"])
        per_case.append({"case_id": cid, "kind": case["kind"], "arm": a, "verdict": v,
                         "expected": case["expected"], "correct": correct})
reruns_per_arm = {a: 0 for a in ("C0", "C1")}
seen = set()
for r in formal:  # count superseded rows per arm (later row wins)
    if (r["case_id"], r["arm"]) in seen: reruns_per_arm[r["arm"]] += 1
    else: seen.add((r["case_id"], r["arm"]))
dups = len(formal) - len(cells)

x1, n1 = acc["C1"]["all"][0], acc["C1"]["all"][1]
x0, n0 = acc["C0"]["all"][0], acc["C0"]["all"][1]
m1 = one_sided_z_test(x1, n1, x0, n0)
m1_pass = (m1["delta"] >= 0.15) and (m1["ci95_lower"] > 0) and (m1["p_value"] < 0.05)
g1r = {a: (g1[a][0] / g1[a][1] if g1[a][1] else 0.0) for a in g1}
g1_pass = g1r["C1"] >= g1r["C0"] - 0.05
g1_degenerate = all(g1[a][0] == 0 for a in g1)
tokm = {a: sum(tok[a]) / len(tok[a]) for a in tok}
wallm = {a: sum(wall[a]) / len(wall[a]) for a in wall}
g2 = {"token_ratio_C1_over_C0": round(tokm["C1"] / tokm["C0"], 4) if tokm["C0"] else None,
      "wall_ratio_C1_over_C0": round(wallm["C1"] / wallm["C0"], 4) if wallm["C0"] else None}
g2_pass = (g2["token_ratio_C1_over_C0"] is not None and g2["token_ratio_C1_over_C0"] <= 1.15
           and g2["wall_ratio_C1_over_C0"] is not None and g2["wall_ratio_C1_over_C0"] <= 1.15)
strat = {a: {k: round(acc[a][k][0] / acc[a][k][1], 4) for k in ("match", "mismatch", "all")} for a in acc}
d_match = strat["C1"]["match"] - strat["C0"]["match"]; d_mis = strat["C1"]["mismatch"] - strat["C0"]["mismatch"]
safety_pass = (d_match >= -0.10) and (d_mis >= -0.10) and (other["C1"] <= other["C0"] + 3) and reruns_per_arm["C1"] <= reruns_per_arm["C0"] + 2  # plan text: C1 rerun count <= C0 + 2

import statistics as _st
walldist = {a: {"median": round(_st.median(wall[a]),3), "p90": round(sorted(wall[a])[int(0.9*len(wall[a]))-1],3)} for a in wall}
if m1_pass and g1_pass and g2_pass and safety_pass: verdict = "QUALIFIED"
elif g2_pass and safety_pass and not m1_pass: verdict = "MECHANISM VISIBLE, EFFICACY NOT QUALIFIED"
elif not g2_pass or not safety_pass: verdict = "GUARDRAIL BREACH - NARROW EXPOSURE"
else: verdict = "MIXED - SEE SPEC §4 PRIORITY"

result = {"spec_sha256": SPEC_SHA256,
          "pool_sha256": hashlib.sha256(json.dumps(pool, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
          "matrix_sha256": hashlib.sha256((HERE / "matrix.jsonl").read_bytes()).hexdigest(),
          "model": "deepseek/deepseek-v4-flash", "n_per_arm": n1,
          "accuracy": strat, "M1": {**{k: round(v, 4) for k, v in m1.items()}, "PASS": m1_pass},
          "G1": {"C1": round(g1r["C1"], 4), "C0": round(g1r["C0"], 4), "PASS": g1_pass, "degenerate_record_use_channel": g1_degenerate},
          "G2": {**g2, "PASS": g2_pass, "mean_tokens": {a: round(tokm[a], 1) for a in tokm}, "mean_wall_s": {a: round(wallm[a], 3) for a in wallm}},
          "wall_dist": walldist, "safety": {"delta_acc_match": round(d_match, 4), "delta_acc_mismatch": round(d_mis, 4),
                     "OTHER": other, "technical_reruns_total": dups, "reruns_per_arm": reruns_per_arm, "PASS": safety_pass},
          "verdict": verdict, "per_case": per_case}
(HERE / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
rs = hashlib.sha256((HERE / "RESULT.json").read_bytes()).hexdigest()
print(json.dumps({k: result[k] for k in ("accuracy", "M1", "G1", "G2", "safety", "verdict")}, ensure_ascii=False, indent=1))
print("RESULT.json sha256 =", rs)
