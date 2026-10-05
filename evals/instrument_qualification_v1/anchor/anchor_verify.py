#!/usr/bin/env python3
"""ANCHOR 一次性裁决：operator 答卷 vs R1，按 ANCHOR-PREREG §3 冻结门槛。"""
import json, pathlib, hashlib, datetime, sys

BASE = pathlib.Path(__file__).resolve().parent.parent
ANCHOR = BASE / "anchor"
meta = json.loads((ANCHOR / "ANCHOR-SAMPLE.json").read_text())
prereg_sha = hashlib.sha256((ANCHOR / "ANCHOR-PREREG.md").read_bytes()).hexdigest()
answers_path = ANCHOR / "ANCHOR-ANSWER.jsonl"

rows = [json.loads(l) for l in answers_path.read_text().splitlines() if l.strip()]
expected_ids = [c["opaque_id"] for c in meta["order"]]
if len(rows) != 12:
    sys.exit(f"[拒绝裁决] 答卷 {len(rows)} 行 ≠ 12")
if [r.get("opaque_id") for r in rows] != expected_ids:
    sys.exit("[拒绝裁决] opaque_id 集或序 ≠ ANCHOR-SAMPLE 呈序")
for r in rows:
    if r.get("verdict") not in ("APPLY", "SKIP"):
        sys.exit(f"[拒绝裁决] 非法 verdict: {r.get('opaque_id')}")
    if not str(r.get("reason", "")).strip():
        sys.exit(f"[拒绝裁决] 理由为空: {r.get('opaque_id')}")

r1 = {}
for l in (BASE / "iq_R1.jsonl").read_text().splitlines():
    d = json.loads(l); r1[d["opaque_id"]] = d["verdict"]

per, agree, a_agree, a_n = [], 0, 0, 0
b19 = None
for c, r in zip(meta["order"], rows):
    hit = r["verdict"] == r1[c["opaque_id"]]
    agree += hit
    if c["cell"] == "A":
        a_n += 1; a_agree += hit
    if c["case_id"] == "iq-B19":
        b19 = {"verdict_op": r["verdict"], "verdict_R1": r1[c["opaque_id"]], "agree": hit,
               "reason_op": r["reason"]}
    per.append({"case_id": c["case_id"], "cell": c["cell"], "op": r["verdict"],
                "R1": r1[c["opaque_id"]], "agree": hit, "reason_op": r["reason"]})

G1 = agree >= 10
G2 = a_agree >= 5
if G1 and G2: verdict = "PASS"
elif agree == 9 or (G1 and not G2): verdict = "HOLD"
else: verdict = "FAIL"

now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
res = {"adjudicated_at": now, "prereg_sha256": prereg_sha, "n": 12,
       "agreement": agree, "G1_pass": G1, "A_agreement": f"{a_agree}/{a_n}", "G2_pass": G2,
       "verdict": verdict, "per_case": per, "B19_disclosure": b19}
(ANCHOR / "ANCHOR-RESULT.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))

md = [f"# ANCHOR 裁决（一次性，{now}）", "",
      f"- verdict：**{verdict}**",
      f"- G1 主门槛：operator×R1 = {agree}/12（门 ≥10）→ {'PASS' if G1 else 'FAIL'}",
      f"- G2 A 格子门：{a_agree}/{a_n}（门 ≥5/6）→ {'PASS' if G2 else 'FAIL'}",
      f"- prereg sha256：{prereg_sha}", "",
      "| case | 格 | operator | R1 | 一致 |", "|---|---|---|---|---|"]
for p in per:
    md.append(f"| {p['case_id']} | {p['cell']} | {p['op']} | {p['R1']} | {'✓' if p['agree'] else '✗'} |")
md += ["", "## B19 披露（PREREG §4）", "",
       f"- operator={b19['verdict_op']}，R1={b19['verdict_R1']}，一致={b19['agree']}；理由：{b19['reason_op']}", "",
       "> 裁决映射见 ANCHOR-PREREG §3：PASS→登记簿追加事件并升级声明；HOLD/FAIL→如实登记不升级。"]
(ANCHOR / "ANCHOR-RESULT.md").write_text("\n".join(md) + "\n")
print(f"verdict={verdict} agreement={agree}/12 A={a_agree}/{a_n}")
