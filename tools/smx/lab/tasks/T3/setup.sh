#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D/out"
cat > "$D/writer.py" <<'PYEOF'
import hashlib
import json
import os
import signal
import time

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
STATE = os.path.join(OUT, ".state")


def write_state(s):
    with open(STATE, "w") as f:
        f.write(s)


def aborted(signum, frame):
    write_state("aborted")
    raise SystemExit(130)


signal.signal(signal.SIGTERM, aborted)
signal.signal(signal.SIGINT, aborted)
write_state("armed")
# 等触发文件出现（出现即开始写入）
while not os.path.exists(os.path.join(D, "start.flag")):
    time.sleep(0.5)
write_state("running")
for k in range(1, 5):
    time.sleep(2)
    with open(os.path.join(OUT, "progress.txt"), "a") as f:
        f.write(f"stage-{k}\n")
payload = f"{os.getpid()}-{time.time()}"
verdict = hashlib.sha256(payload.encode()).hexdigest()[:12]
body = json.dumps({"verdict": verdict, "stages": 4}).encode()
with open(os.path.join(OUT, "result.json"), "wb") as f:
    f.write(body)
with open(os.path.join(OUT, ".result-sha"), "w") as f:
    f.write(hashlib.sha256(body).hexdigest())
with open(os.path.join(OUT, "done.flag"), "w") as f:
    f.write(f"done-by-writer-{os.getpid()}\n")
write_state("completed")
PYEOF
shasum -a 256 "$D/writer.py" | awk '{print $1}' > "$D/.fixture-writer-sha"
cd "$D"
nohup python3 writer.py > out/writer.log 2>&1 &
echo $! > out/.writer-pid
