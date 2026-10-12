"""IQ v1 mechanical builder — IQ-V1-PREREG.md §3/§6 (FROZEN 2026-10-05). Zero provider.
Outputs: iq_candidates.json (full facts; not shown to raters before unseal),
iq_sealed.json (salt + mapping; sha256 printed, content NOT printed),
iq_sheet.md (blind sheet; R1/R2 identical order).
B-cell pairing replicates v1 build_pool.py CODE BEHAVIOR verbatim (incl. its
lexicographic-max tie-break, see PREREG §10 implementation note); build self-check
demands 20/20 reproduction of v1 mismatch pairings.
"""
import hashlib, json, pathlib, random, re, secrets
from datetime import datetime, timezone, timedelta

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METHODS = ROOT / "data" / "methods"
V1_POOL = ROOT / "evals" / "method_binding_efficacy_v1" / "pool.json"
SEED = 20261005

PREREG_SHA256 = hashlib.sha256((HERE / "IQ-V1-PREREG.md").read_bytes()).hexdigest()

def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

# === v1 frozen primitives — copied verbatim from evals/method_binding_efficacy_v1/build_pool.py ===
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
            "content_sha256": hashlib.sha256(raw.encode()).hexdigest()}

def bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i+2] for i in range(len(s) - 1)}

def ov(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / min(len(A), len(B)) if A and B else 0.0

def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if A | B else 0.0

# === card universe & selection — verbatim v1 rule ===
cards = []
for p in sorted(METHODS.glob("*/METHOD.md")):
    c = parse_card(p)
    if c and c["trigger"]: cards.append(c)

rank = {"qualified": 0, "active": 1, "candidate": 2, "hold": 3, "retired": 4}
cards.sort(key=lambda c: (rank.get(c["status"], 9), c["method_id"]))
selected, seen = [], set()
for c in cards:
    if c["method_id"] in seen: continue
    selected.append(c); seen.add(c["method_id"])
    if len(selected) == 20: break
assert len(selected) == 20, f"card selection failed: {len(selected)}"

def find_partner(c, mode):
    """v1 rule verbatim: candidates = all cards, exclude self/retired/hold and
    twins J(trigger_j, trigger_i) > 0.35; score = ov(trigger_j, description_i).
    mode='max': tie behavior = v1 CODE (score, method_id) lexicographic MAX.
    mode='min': new D-cell code, tie = method_id ASC (per PREREG §3/§10)."""
    best = None
    for o in cards:
        if o["method_id"] == c["method_id"] or o["status"] in ("retired", "hold"): continue
        if jac(o["trigger"], c["trigger"]) > 0.35: continue
        score = ov(o["trigger"], c["description"])
        key = (score, o["method_id"])
        if best is None or (key > (best[0], best[1]) if mode == "max" else key < (best[0], best[1])):
            best = (score, o["method_id"], o)
    assert best is not None, f"no partner for {c['method_id']}"
    return best

ov_self = {c["method_id"]: ov(c["trigger"], c["description"]) for c in selected}
desc_order = sorted(selected, key=lambda c: (-ov_self[c["method_id"]], c["method_id"]))
asc_order  = sorted(selected, key=lambda c: ( ov_self[c["method_id"]], c["method_id"]))
A_cards, D_cards, C_cards = desc_order[:6], desc_order[8:14], asc_order[:8]

def mk(cell, idx, subj, trig_card, intended, extra=None):
    card = f"name: {subj['name']}\nmethod_id: {subj['method_id']}\ndescription: {subj['description']}\n\n{subj['body']}"
    d = {"case_id": f"iq-{cell}{idx:02d}", "cell": cell, "subject": subj["method_id"],
         "trigger": trig_card["trigger"], "trigger_source": trig_card["method_id"],
         "card": card, "intended": intended,
         "content_sha256": subj["content_sha256"], "status": subj["status"]}
    if extra: d.update(extra)
    return d

cases = []
for i, c in enumerate(A_cards):
    cases.append(mk("A", i+1, c, c, "APPLY", {"ov_self": round(ov_self[c["method_id"]], 4)}))

v1 = json.loads(V1_POOL.read_text(encoding="utf-8"))
repro_ok = repro_n = 0
for i, c in enumerate(selected):
    score, pid, pcard = find_partner(c, "max")
    vc = v1["cases"].get(f"mb-{i*2+2:03d}")
    repro_n += 1
    if vc and vc["trigger_source"] == pid and abs(round(score, 4) - vc["trap_overlap_trigger_vs_subject"]) < 1e-9:
        repro_ok += 1
    cases.append(mk("B", i+1, c, pcard, "SKIP",
                    {"ov_self": round(ov_self[c["method_id"]], 4), "trap_overlap": round(score, 4),
                     "v1_case_ref": f"mb-{i*2+2:03d}"}))
assert repro_ok == repro_n == 20, f"v1 pairing reproduction failed: {repro_ok}/{repro_n}"

for i, c in enumerate(C_cards):
    cases.append(mk("C", i+1, c, c, "APPLY", {"ov_self": round(ov_self[c["method_id"]], 4)}))
for i, c in enumerate(D_cards):
    score, pid, pcard = find_partner(c, "min")
    cases.append(mk("D", i+1, c, pcard, "SKIP",
                    {"ov_self": round(ov_self[c["method_id"]], 4), "min_overlap": round(score, 4)}))
assert len(cases) == 40

seal_salt = secrets.token_hex(16)
for c in cases:
    c["opaque_id"] = hashlib.sha256((c["case_id"] + "|" + seal_salt).encode()).hexdigest()[:12]
assert len({c["opaque_id"] for c in cases}) == 40

order = list(range(40))
random.Random(SEED).shuffle(order)
presented = [cases[i] for i in order]

QUESTION = "假设你正在执行下面的【任务】，手头只有这张【方法卡】。该卡对本任务是否适用？\nAPPLY = 采纳其指引会实质改变/正确化本任务的执行；SKIP = 不适用。\n请附一行理由。"
lines = [f"# IQ v1 盲评表（40 例；呈序 seed={SEED}；R1/R2 同序同文；开封前互不交流、不看 iq_sealed.json/iq_candidates.json/FORENSIC*）", "",
         "> " + QUESTION.replace("\n", "\n> "), "",
         "**答卷**：`iq_R1.jsonl`（或 `iq_R2.jsonl`），每行一个 JSON 对象：", '`{"opaque_id":"…","verdict":"APPLY|SKIP","reason":"一行理由","ts":"ISO时间"}' + "`", ""]
for n, c in enumerate(presented, 1):
    lines += [f"## {n}. `{c['opaque_id']}`", "", "**【任务】**", "", c["trigger"], "",
              "**【方法卡】**", "", "````", c["card"], "````", "",
              f"- verdict(`{c['opaque_id']}`)：APPLY / SKIP　理由：…", ""]
(HERE / "iq_sheet.md").write_text("\n".join(lines), encoding="utf-8")

ts = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
candidates = {"prereg_sha256": PREREG_SHA256, "seed": SEED, "built_at": ts,
              "cells": {"A": 6, "B": 20, "C": 8, "D": 6},
              "v1_pairing_reproduced": f"{repro_ok}/{repro_n}",
              "cases": {c["case_id"]: {k: v for k, v in c.items()} for c in cases}}
sealed = {"prereg_sha256": PREREG_SHA256, "seal_salt": seal_salt, "built_at": ts,
          "v1_pairing_reproduced": f"{repro_ok}/{repro_n}",
          "present_order": [c["opaque_id"] for c in presented],
          "cases": {c["opaque_id"]: {"case_id": c["case_id"], "cell": c["cell"], "intended": c["intended"],
                                     "subject": c["subject"], "trigger_source": c["trigger_source"],
                                     **{k: c[k] for k in ("v1_case_ref", "ov_self", "trap_overlap", "min_overlap") if k in c}}
                    for c in cases}}
(HERE / "iq_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")
(HERE / "iq_sealed.json").write_text(json.dumps(sealed, ensure_ascii=False, indent=1), encoding="utf-8")

print("prereg_sha256        =", PREREG_SHA256)
print("candidates_sha256    =", sha256_json(candidates))
print("sealed_sha256        =", sha256_json(sealed))
print("sheet_sha256(file)   =", hashlib.sha256((HERE / "iq_sheet.md").read_bytes()).hexdigest())
print("v1_pairing_reproduced=", f"{repro_ok}/{repro_n}")
print("cells                =", {x: sum(c["cell"] == x for c in cases) for x in "ABCD"})
print("outputs              = iq_candidates.json / iq_sealed.json / iq_sheet.md")
