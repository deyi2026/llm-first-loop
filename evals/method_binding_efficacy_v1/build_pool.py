"""Mechanical case-pool construction (pre-run, deterministic). Rule set pre-registered in EXECUTION-PLAN.md."""
import json, pathlib, random, re, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from protocol import SEED, sha256_json

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
METHODS = ROOT / "data" / "methods"

def parse_card(p: pathlib.Path):
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m: return None
    meta_txt, body = m.group(1), m.group(2)
    def scal(k):
        mm = re.search(rf"^{k}:\s*(.+)$", meta_txt, re.M)
        return mm.group(1).strip() if mm else ""
    status = scal("status").lower() or "candidate"
    name, mid, desc = scal("name"), scal("method_id"), scal("description")
    tg = re.search(r"## Trigger\s*\n(.*?)(?=\n## |\Z)", body, re.S)
    if not (name and mid and desc and tg): return None
    return {"method_id": mid, "name": name, "status": status, "description": desc,
            "trigger": tg.group(1).strip(), "body": body.strip(),
            "content_sha256": __import__("hashlib").sha256(raw.encode()).hexdigest()}

cards = []
for p in sorted(METHODS.glob("*/METHOD.md")):
    c = parse_card(p)
    if c and c["trigger"]: cards.append(c)

rank = {"qualified": 0, "active": 1, "candidate": 2, "hold": 3, "retired": 4}
cards.sort(key=lambda c: (rank.get(c["status"], 9), c["method_id"]))
selected, seen = [], set()
for c in cards:                                   # lifecycle rank first, then method_id asc; 20 cards
    if c["method_id"] in seen: continue
    selected.append(c); seen.add(c["method_id"])
    if len(selected) == 20: break
assert len(selected) == 20, f"pool selection failed: {len(selected)}"

def bigrams(s): 
    s = re.sub(r"\s+", "", s)
    return {s[i:i+2] for i in range(len(s) - 1)}

def ov(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / min(len(A), len(B)) if A and B else 0.0

def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if A | B else 0.0

cases = []
for i, c in enumerate(selected):
    # match case: card's own trigger, expect APPLY
    cases.append({"case_id": f"mb-{i*2+1:03d}", "kind": "match", "method_ref": "method:" + c["method_id"],
                  "trigger_source": c["method_id"], "trigger": c["trigger"],
                  "card": f"name: {c['name']}\nmethod_id: {c['method_id']}\ndescription: {c['description']}\n\n{c['body']}",
                  "expected": "APPLY", "content_sha256": c["content_sha256"], "status": c["status"]})
    # mismatch case: partner = argmax over ALL cards of J(bigrams(trigger_j), card_i_text),
    # constrained by J(trigger_j, trigger_i) <= 0.35 (exclude same-subject twins); tie-break method_id asc
    ci_text = c["description"] + c["body"]
    best = None
    for o in cards:
        if o["method_id"] == c["method_id"] or o["status"] in ("retired", "hold"): continue
        t_sim = jac(o["trigger"], c["trigger"])
        if t_sim > 0.35: continue
        score = ov(o["trigger"], c["description"])   # overlap coefficient: trap vs card SUBJECT statement
        key = (score, o["method_id"])
        if best is None or key > (best[0], best[1]): best = (score, o["method_id"], o)
    j, pid, partner = best
    cases.append({"case_id": f"mb-{i*2+2:03d}", "kind": "mismatch", "method_ref": "method:" + c["method_id"],
                  "trigger_source": pid, "trigger": partner["trigger"],
                  "card": f"name: {c['name']}\nmethod_id: {c['method_id']}\ndescription: {c['description']}\n\n{c['body']}",
                  "expected": "SKIP", "trap_overlap_trigger_vs_subject": round(j, 4), "trigger_self_jaccard": round(jac(partner["trigger"], c["trigger"]), 4),
                  "pairing_rule": "global_argmax_trigger_vs_card_twin_excluded", "content_sha256": c["content_sha256"], "status": c["status"]})

order = [c["case_id"] for c in cases]
random.Random(SEED).shuffle(order)
pool = {"spec_sha256": __import__("protocol").SPEC_SHA256, "seed": SEED, "n_cases": len(cases),
        "selection_rule": "lifecycle rank qualified>active>candidate>hold>retired, tie-break method_id asc, first 20",
        "pairing_rule": "partner = argmax_{j!=i, status not in (retired,hold), J(trigger_j,trigger_i)<=0.35} overlap_coefficient(bigrams(trigger_j), bigrams(description_i)), tie-break method_id asc",
        "label_noise_note": "mismatch 高重叠配对存在真双适用标签噪声风险；paired 同案双臂下 M1 差值不受影响，绝对正确率按下界解读",
        "cases": {c["case_id"]: c for c in cases}, "run_order": order}
out = pathlib.Path(__file__).resolve().parent / "pool.json"
out.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
print("pool_sha256 =", sha256_json(pool))
print("cases:", len(cases), "| match:", sum(c['kind']=='match' for c in cases), "| mismatch:", sum(c['kind']=='mismatch' for c in cases))
print("mismatch J(trigger,card) min/mean/max:", min(c["trap_overlap_trigger_vs_subject"] for c in cases if c["kind"]=="mismatch"), round(sum(c["trap_overlap_trigger_vs_subject"] for c in cases if c["kind"]=="mismatch")/20,4), max(c["trap_overlap_trigger_vs_subject"] for c in cases if c["kind"]=="mismatch"))
