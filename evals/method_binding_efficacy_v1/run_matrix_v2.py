#!/usr/bin/env python3
"""Orchestrator v2: D4 root-fixed (healthcheck.is_healthy), strict YES/NO smoke gate.
Protocol/pool/order/interleave unchanged vs v1. DATA_DIR env + bare LLM_MODEL kept (empirical, worker-asserted)."""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from protocol import MODEL, SMOKE_RE
from healthcheck import is_healthy

def child_env(arm):
    e = dict(os.environ)
    e.pop("LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL", None)
    if arm == "C1": e["LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL"] = "1"
    e["LLM_MODEL"] = MODEL
    e["DATA_DIR"] = str((HERE / "run_data").resolve())  # DATA_DIR env wins over toml lfl_data_dir (empirical)
    return e

def run_child(arm, extra, timeout=420):
    cmd = [sys.executable, str(HERE / "worker.py"), "--arm", arm, "--out", str(HERE / "matrix.jsonl"), *extra]
    try:
        cp = subprocess.run(cmd, env=child_env(arm), capture_output=True, text=True, timeout=timeout, cwd=str(HERE))
        return cp.returncode, (cp.stdout + cp.stderr).strip()[-400:]
    except subprocess.TimeoutExpired:
        return 124, "orchestrator timeout 420s"

def read_rows():
    p = HERE / "matrix.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

pool = json.loads((HERE / "pool.json").read_text())
ps = hashlib.sha256(json.dumps(pool, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
freeze = json.loads((HERE / "pool.freeze.json").read_text())
assert ps == freeze["pool_sha256"], "POOL TAMPERED vs freeze"
log = {"pool_sha256": ps, "model": MODEL, "steps": []}

# --- precondition 1: surface diff confined to save_experience ---
for arm in ("C0", "C1"):
    rc, out = run_child(arm, ["--surface-only"])
    log["steps"].append({"step": "surface", "arm": arm, "rc": rc, "tail": out[-120:]})
rows = [r for r in read_rows() if r["kind"] == "surface_only" and r.get("status") == "SURFACE_ONLY"]
assert len(rows) >= 2, f"surface rows missing: {rows}"
s0, s1 = rows[-2]["surface"], rows[-1]["surface"]
assert rows[-2]["arm"] == "C0" and rows[-1]["arm"] == "C1", [r["arm"] for r in rows]
assert set(s0) == set(s1), f"tool set differs: {set(s0) ^ set(s1)}"
diff = {k for k in s0 if s0[k] != s1[k]}
log["surface_diff_tools"] = sorted(diff)
if diff != {"save_experience"}:
    log["abort"] = f"surface diff not confined: {diff}"
    (HERE / "ABORT.json").write_text(json.dumps(log, ensure_ascii=False, indent=1)); sys.exit(2)

# --- precondition 2+3: smoke gates ---
smoke_rows = []
for i in range(5):
    for arm in ("C0", "C1"):
        rc, out = run_child(arm, ["--smoke"])
        log["steps"].append({"step": "smoke", "i": i, "arm": arm, "rc": rc, "tail": out[-80:]})
smokes = [r for r in read_rows() if r["kind"] == "smoke" and r.get("status") == "RUN_OK"][-10:]
c0 = [r for r in smokes if r["arm"] == "C0"]; c1 = [r for r in smokes if r["arm"] == "C1"]
log["smoke_raw"] = {"C0": [r["final_answer"][:40] for r in c0], "C1": [r["final_answer"][:40] for r in c1]}
def smoke_word(t):
    m = SMOKE_RE.search(t or "")
    return m.group(1) if m else None
ok_c0 = all(smoke_word(r["final_answer"]) == "NO" for r in c0) and len(c0) == 5
ok_c1 = all(smoke_word(r["final_answer"]) == "YES" for r in c1) and len(c1) == 5
log["smoke_gates"] = {"C0_missing_5of5": ok_c0, "C1_visible_5of5": ok_c1}
if not (ok_c0 and ok_c1):
    log["abort"] = "smoke gate failed"
    (HERE / "ABORT.json").write_text(json.dumps(log, ensure_ascii=False, indent=1)); sys.exit(3)

# --- formal matrix: interleaved C0->C1 per case, seed-frozen order; 1 technical rerun max ---
def formal_done(rows, cid, arm):
    return [r for r in rows if r["kind"] == "formal" and r["case_id"] == cid and r["arm"] == arm]

healthy = is_healthy  # v2: canonical compare, fixes D4 double-run

for n, cid in enumerate(pool["run_order"], 1):
    for arm in ("C0", "C1"):
        rc, out = run_child(arm, ["--case-id", cid])
        row = formal_done(read_rows(), cid, arm)[-1]
        if not healthy(row):
            rc2, out2 = run_child(arm, ["--case-id", cid])
            log["steps"].append({"step": "formal-rerun", "case": cid, "arm": arm, "rc1": rc, "rc2": rc2, "tail": (out + " | " + out2)[-160:]})
    if n % 10 == 0: log["steps"].append({"step": "progress", "n": n, "ts": time.strftime("%H:%M:%S")})

rows = [r for r in read_rows() if r["kind"] == "formal"]
log["formal_rows_total"] = len(rows)
log["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
(HERE / "execution_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
print("MATRIX DONE", len(rows), "formal rows")
