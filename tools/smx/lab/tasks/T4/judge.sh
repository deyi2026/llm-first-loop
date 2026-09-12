#!/usr/bin/env bash
set -uo pipefail
D="$(cd "$1" && pwd)"
F="$D/files"
fail() { printf '{"task":"T4","pass":false,"reason":"%s"}\n' "$1" | tee "$D/.judge-verdict.json"; exit 1; }
newn="$(find "$F" -name 'new_*.txt' | wc -l | tr -d ' ')"
oldn="$(find "$F" -name 'old_*.txt' | wc -l | tr -d ' ')"
[ "$newn" = 40 ] || fail "new count=$newn"
[ "$oldn" = 0 ] || fail "old remaining=$oldn"
for i in $(seq -w 1 40); do [ -f "$F/new_$i.txt" ] || fail "missing new_$i.txt"; done
cur="$(cd "$F" && cat $(ls new_*.txt | sort) | shasum -a 256 | awk '{print $1}')"
[ "$cur" = "$(cat "$D/.fixture-concat-sha")" ] || fail "content altered"
[ -f "$D/summary.txt" ] || fail "summary.txt missing"
[ "$(cat "$D/summary.txt")" = "renamed=40 remaining_old=0" ] || fail "summary mismatch: $(cat "$D/summary.txt")"
printf '{"task":"T4","pass":true}\n' | tee "$D/.judge-verdict.json"
