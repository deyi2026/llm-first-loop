#!/usr/bin/env bash
# freeze.sh — 记录冻结件 sha256 到 lab/FREEZE.json（闸门0 收尾）
set -euo pipefail
LAB="$(cd "$(dirname "$0")" && pwd)"
python3 - "$LAB" <<'PYEOF'
import hashlib, json, os, sys, time
lab = sys.argv[1]
files = ["harness.sh", "metrics.py", "selftest.sh", "PROTOCOL-20260911.md",
         "config.card", "config-b.card", "tasks/_shared/appendix-B.md"]
for i in range(1, 7):
    for n in ("setup.sh", "judge.sh", "task.md"):
        files.append(f"tasks/T{i}/{n}")
rec = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
       "note": "gate-0 freeze; any change after this invalidates the round",
       "files": {}}
for rel in files:
    p = os.path.join(lab, rel)
    rec["files"][rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
out = os.path.join(lab, "FREEZE.json")
json.dump(rec, open(out, "w"), ensure_ascii=False, indent=1)
print(f"{len(rec['files'])} files -> {out}")
PYEOF
