"""IQ v1 analyzer — IQ-V1-PREREG.md §5/§6 frozen gates. One-shot, zero provider.
Inputs: iq_sealed.json + iq_R1.jsonl + iq_R2.jsonl (both complete, before unseal).
Outputs: IQ-RESULT.json / IQ-RESULT.md.
Gate semantics (frozen §5): certified = R1 AND R2 both == intended; adjudication
never rescues certification; disagreements logged with R1 final reason only.
"""
import json, pathlib, random, sys
from datetime import datetime, timezone, timedelta
import hashlib

HERE = pathlib.Path(__file__).resolve().parent
SEED = 20261005
BOOTSTRAP_N = 10000

def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

sealed = json.loads((HERE / "iq_sealed.json").read_text(encoding="utf-8"))

def load_ratings(path):
    rs = {}
    for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln: continue
        r = json.loads(ln)
        assert r["verdict"] in ("APPLY", "SKIP"), f"bad verdict: {r}"
        assert r["opaque_id"] not in rs, f"duplicate: {r['opaque_id']}"
        rs[r["opaque_id"]] = (r["verdict"], str(r.get("reason", "")))
    return rs

R1, R2 = load_ratings(HERE / "iq_R1.jsonl"), load_ratings(HERE / "iq_R2.jsonl")
need = set(sealed["cases"])
assert set(R1) == need and set(R2) == need, \
    f"rating sets mismatch: R1 missing {need - set(R1)}, extra {set(R1) - need}; R2 missing {need - set(R2)}, extra {set(R2) - need}"

ids = sealed["present_order"]
assert set(ids) == need and len(ids) == 40
r1 = [R1[i][0] for i in ids]
r2 = [R2[i][0] for i in ids]
cases = sealed["cases"]

def kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((sum(x == c for x in a) / n) * (sum(y == c for y in b) / n) for c in ("APPLY", "SKIP"))
    return (po - pe) / (1 - pe) if pe < 1 else 1.0

k = kappa(r1, r2)
po = sum(x == y for x, y in zip(r1, r2)) / 40
rng = random.Random(SEED)
bs = []
for _ in range(BOOTSTRAP_N):
    idx = rng.choices(range(40), k=40)
    try:
        bs.append(kappa([r1[i] for i in idx], [r2[i] for i in idx]))
    except ZeroDivisionError:
        pass
bs.sort()
ci_lo, ci_hi = bs[int(0.025 * len(bs))], bs[min(int(0.975 * len(bs)), len(bs) - 1)]

cert = {i: (R1[i][0] == R2[i][0] == cases[i]["intended"]) for i in ids}
per_cell, cell_rows = {}, {}
for cell in "ABCD":
    cell_ids = [i for i in ids if cases[i]["cell"] == cell]
    n = len(cell_ids)
    c_n = sum(cert[i] for i in cell_ids)
    r1_int = sum(R1[i][0] == cases[i]["intended"] for i in cell_ids)
    r2_int = sum(R2[i][0] == cases[i]["intended"] for i in cell_ids)
    per_cell[cell] = {"n": n, "certified": c_n, "r1_intended": r1_int, "r2_intended": r2_int}
    cell_rows[cell] = cell_ids

acd_ids = [i for i in ids if cases[i]["cell"] in "ACD"]  # A6+C8+D6 = 20 构造确定例
r1_acd = sum(R1[i][0] == cases[i]["intended"] for i in acd_ids)
r1_acd_rate = r1_acd / len(acd_ids)
disagree = [i for i in ids if R1[i][0] != R2[i][0]]

gates = {}
gates["Q1_kappa"] = {"value": round(k, 4), "ci95": [round(ci_lo, 4), round(ci_hi, 4)],
                     "raw_agreement": round(po, 4), "status": "PASS" if k >= 0.70 else ("HOLD" if k >= 0.55 else "FAIL")}
gates["R1_vs_intended_ACD"] = {"value": round(r1_acd_rate, 4), "threshold": 0.90,
                               "status": "PASS" if r1_acd_rate >= 0.90 else "HOLD"}
gates["A_cert"] = {"value": per_cell["A"]["certified"], "threshold": ">=5/6",
                   "status": "PASS" if per_cell["A"]["certified"] >= 5 else "ALERT_REVIEW"}
gates["D_cert"] = {"value": per_cell["D"]["certified"], "threshold": ">=5/6",
                   "status": "PASS" if per_cell["D"]["certified"] >= 5 else "ALERT_REVIEW"}
gates["B_cert"] = {"value": per_cell["B"]["certified"], "threshold": ">=12/20",
                   "status": "PASS" if per_cell["B"]["certified"] >= 12 else "TRIGGER_REPLACE"}
gates["C_cert"] = {"value": per_cell["C"]["certified"], "threshold": ">=6/8",
                   "status": "PASS" if per_cell["C"]["certified"] >= 6 else "TRIGGER_REPLACE"}
gates["disagreement"] = {"value": len(disagree), "rate": round(len(disagree) / 40, 4), "threshold": "<=6/40",
                         "status": "PASS" if len(disagree) <= 6 else "JOINT_WITH_KAPPA"}
H_plus, H_minus = per_cell["B"]["certified"], per_cell["C"]["certified"]
gates["Q3_headroom"] = {"H_plus": H_plus, "H_plus_threshold": 12, "H_minus": H_minus, "H_minus_threshold": 6,
                        "status": "PASS" if (H_plus >= 12 and H_minus >= 6) else "FAIL"}

Q1 = gates["Q1_kappa"]["status"]
Q2_pass = all(gates[g]["status"] == "PASS" for g in ("A_cert", "D_cert", "B_cert", "C_cert"))
Q2 = "PASS" if Q2_pass else "FAIL"   # gate-level nuance (ALERT_REVIEW / TRIGGER_REPLACE) reported alongside
Q3 = gates["Q3_headroom"]["status"]
verdict = ("PASS" if (Q1 == "PASS" and Q2 == "PASS" and Q3 == "PASS")
           else ("HOLD" if Q1 == "HOLD" else "FAIL"))
# any hard FAIL dominates HOLD semantics
if Q1 == "FAIL" or Q2 == "FAIL" or Q3 == "FAIL": verdict = "FAIL"

disagree_rows = [{"opaque_id": i, "cell": cases[i]["cell"], "intended": cases[i]["intended"],
                  "case_id": cases[i]["case_id"], "R1": R1[i][0], "R1_reason": R1[i][1],
                  "R2": R2[i][0], "R2_reason": R2[i][1]} for i in disagree]

ts = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
result = {"analyzed_at": ts, "prereg_sha256": sealed["prereg_sha256"], "sealed_sha256": sha256_json(sealed),
          "n": 40, "kappa": round(k, 4), "kappa_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
          "raw_agreement": round(po, 4), "bootstrap_n": BOOTSTRAP_N, "bootstrap_seed": SEED,
          "per_cell": per_cell, "R1_vs_intended_ACD": round(r1_acd_rate, 4),
          "gates": gates, "Q1": Q1, "Q2": Q2, "Q3": Q3, "verdict": verdict,
          "disagreements": disagree_rows,
          "certified_B_case_ids": sorted(cases[i]["case_id"] for i in ids if cases[i]["cell"] == "B" and cert[i]),
          "disclosure": "R2 非独立（L/D 归类作者、设计作者、评前已知 FORENSIC 内容）——载重结论挂 R1 与 κ（PREREG §8.1）",
          "verdict_note": "PASS ⇒ 构造器 v2 挂 IQ-CTOR-v2；κ HOLD ⇒ 单轮指引修订+整表重评；任一 FAIL ⇒ 构造器/仪器重做；B/C 短缺 ⇒ 单轮替换（≤6/格，二轮仍短缺=构造器 FAIL）"}
(HERE / "IQ-RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

md = [f"# IQ v1 结果（一次性裁决，{ts}）", "",
      f"- verdict：**{verdict}**（Q1={Q1} / Q2={Q2} / Q3={Q3}）",
      f"- κ(R1,R2) = {k:.4f}，95%CI [{ci_lo:.4f}, {ci_hi:.4f}]，raw agreement = {po:.4f}（{40 - len(disagree)}/40）",
      f"- R1 vs intended（A/C/D 构造确定 {len(acd_ids)} 例）= {r1_acd}/{len(acd_ids)} = {r1_acd_rate:.3f}",
      f"- 认证（双评一致判出 intended）：A {per_cell['A']['certified']}/6｜B {per_cell['B']['certified']}/20｜C {per_cell['C']['certified']}/8｜D {per_cell['D']['certified']}/6",
      f"- headroom：H⁺ = {H_plus}（门 ≥12）｜H⁻ = {H_minus}（门 ≥6）",
      f"- 分歧：{len(disagree)}/40（门 ≤6）", "",
      "## 门槛明细", "",
      "| gate | 值 | 阈值 | 状态 |", "|---|---|---|---|"]
for g, v in gates.items():
    if g == "Q1_kappa":
        val, thr = f"{v['value']} (CI95 {v['ci95']}, po {v['raw_agreement']})", ">=0.70 (0.55-0.70 HOLD)"
    elif g == "Q3_headroom":
        val, thr = f"H⁺={v['H_plus']}, H⁻={v['H_minus']}", "H⁺>=12, H⁻>=6"
    else:
        val, thr = v["value"], v["threshold"]
    md.append(f"| {g} | {val} | {thr} | {v['status']} |")
md += ["", "## 分歧清单（裁定不救认证；R1 理由留痕归因）", ""]
if disagree_rows:
    md.append("| opaque | cell | intended | R1 | R2 | R1 reason |")
    md.append("|---|---|---|---|---|---|")
    for d in disagree_rows:
        md.append(f"| `{d['opaque_id']}` | {d['cell']} | {d['intended']} | {d['R1']} | {d['R2']} | {d['R1_reason']} |")
else:
    md.append("（无分歧）")
md += ["", f"> 披露：{result['disclosure']}", f"> {result['verdict_note']}"]
(HERE / "IQ-RESULT.md").write_text("\n".join(md), encoding="utf-8")
print("verdict =", verdict, "| Q1 =", Q1, "| Q2 =", Q2, "| Q3 =", Q3)
print("kappa =", round(k, 4), "CI95 [", round(ci_lo, 4), ",", round(ci_hi, 4), "] po =", round(po, 4))
print("cert  = A %d/6 B %d/20 C %d/8 D %d/6" % (per_cell['A']['certified'], per_cell['B']['certified'], per_cell['C']['certified'], per_cell['D']['certified']))
print("outputs: IQ-RESULT.json / IQ-RESULT.md")
