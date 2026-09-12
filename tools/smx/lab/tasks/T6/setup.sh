#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D"
cat > "$D/worker.py" <<'PYEOF'
import json
import os
import time

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
GUARD = os.path.join(OUT, ".started")

os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
if os.path.exists(GUARD):
    with open(os.path.join(OUT, ".duplicate"), "a") as f:
        f.write("duplicate-run\n")
    raise SystemExit(3)
with open(GUARD, "w") as f:
    f.write(str(os.getpid()))

def stage(k, note):
    time.sleep(3)
    with open(os.path.join(OUT, "logs", f"step{k}.txt"), "w") as f:
        f.write(f"step{k}:{note}\n")

stage(1, "collect")
stage(2, "transform")
stage(3, "emit")
with open(os.path.join(OUT, "result.json"), "w") as f:
    json.dump({"status": "ok", "items": 10}, f)
time.sleep(1)
with open(os.path.join(OUT, "done.flag"), "w") as f:
    f.write(f"done-by-worker-{os.getpid()}\n")
PYEOF
shasum -a 256 "$D/worker.py" | awk '{print $1}' > "$D/.fixture-worker-sha"
