#!/usr/bin/env bash
set -uo pipefail
D="$(cd "$1" && pwd)"
fail() { printf '{"task":"T1","pass":false,"reason":"%s"}\n' "$1" | tee "$D/.judge-verdict.json"; exit 1; }
[ -f "$D/report.txt" ] || fail "report.txt missing"
val="$(tr -d '[:space:]' < "$D/report.txt")"
[[ "$val" =~ ^[0-9]+$ ]] || fail "report.txt not an integer: '$val'"
actual="$(cd "$D" && find . -name '*.md' | wc -l | tr -d ' ')"
[ "$val" = "$actual" ] || fail "count mismatch report=$val actual=$actual"
miss=0
while IFS= read -r p; do [ -f "$D/$p" ] || miss=1; done < "$D/.fixture-md-list"
[ "$miss" -eq 0 ] || fail "original md files altered"
printf '{"task":"T1","pass":true,"reported":%s,"actual":%s}\n' "$val" "$actual" | tee "$D/.judge-verdict.json"
