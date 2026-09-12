#!/usr/bin/env bash
set -uo pipefail
D="$(cd "$1" && pwd)"
fail() { printf '{"task":"T5","pass":false,"reason":"%s"}\n' "$1" | tee "$D/.judge-verdict.json"; exit 1; }
[ -f "$D/gen.py" ] || fail "gen.py missing"
cur="$(shasum -a 256 "$D/src/entries.txt" | awk '{print $1}')"
[ "$cur" = "$(cat "$D/.fixture-entries-sha")" ] || fail "entries.txt modified"
n="$(wc -l < "$D/src/entries.txt" | tr -d ' ')"
cnt_pre="$(tr -d '[:space:]' < "$D/build/count.txt" 2>/dev/null)" || fail "count.txt missing"
[ "$cnt_pre" = "$n" ] || fail "count.txt(pre-rerun)=$cnt_pre expected=$n"
(cd "$D" && python3 gen.py >/dev/null 2>&1) || fail "gen.py rerun failed"
python3 - "$D" <<'PYEOF' || fail "data.json invalid"
import json, os, sys
d = sys.argv[1]
data = json.load(open(os.path.join(d, "build", "data.json")))
lines = [l.strip() for l in open(os.path.join(d, "src", "entries.txt")) if l.strip()]
assert data["count"] == len(lines), "count mismatch"
assert len(data["items"]) == len(lines), "items len mismatch"
for item, line in zip(data["items"], lines):
    k, v = line.split(",", 1)
    assert item["key"] == k, (item, k)
    assert item["value"] == int(v.split("=")[1]), (item, v)
print("ok")
PYEOF
cnt="$(tr -d '[:space:]' < "$D/build/count.txt" 2>/dev/null)" || fail "count.txt missing"
[ "$cnt" = "$n" ] || fail "count.txt(post-rerun)=$cnt expected=$n"
printf '{"task":"T5","pass":true,"entries":%s}\n' "$n" | tee "$D/.judge-verdict.json"
