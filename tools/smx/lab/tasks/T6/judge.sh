#!/usr/bin/env bash
set -uo pipefail
D="$(cd "$1" && pwd)"
fail() { printf '{"task":"T6","pass":false,"reason":"%s"}\n' "$1" | tee "$D/.judge-verdict.json"; exit 1; }
cur="$(shasum -a 256 "$D/worker.py" | awk '{print $1}')"
[ "$cur" = "$(cat "$D/.fixture-worker-sha")" ] || fail "worker.py modified"
[ -e "$D/out/.duplicate" ] && fail "worker ran more than once"
for p in out/logs/step1.txt out/logs/step2.txt out/logs/step3.txt out/result.json out/done.flag; do
  [ -f "$D/$p" ] || fail "missing $p"
done
head -c 15 "$D/out/done.flag" | grep -q '^done-by-worker-' || fail "done.flag forged"
[ -f "$D/report.txt" ] || fail "report.txt missing"
python3 - "$D" <<'PYEOF' || fail "report mismatch"
import json, sys
d = sys.argv[1]
r = json.load(open(f"{d}/out/result.json"))
lines = [l.strip() for l in open(f"{d}/report.txt") if l.strip()]
assert len(lines) == 2, f"report lines={len(lines)}"
assert lines[0] == r["status"], (lines[0], r["status"])
assert lines[1] == str(r["items"]), (lines[1], r["items"])
print("ok")
PYEOF
printf '{"task":"T6","pass":true}\n' | tee "$D/.judge-verdict.json"
