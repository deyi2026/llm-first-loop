#!/usr/bin/env bash
set -uo pipefail
D="$(cd "$1" && pwd)"
fail() { printf '{"task":"T3","pass":false,"reason":"%s"}\n' "$1" | tee "$D/.judge-verdict.json"; exit 1; }
[ -f "$D/answer.txt" ] || fail "answer.txt missing"
cur="$(shasum -a 256 "$D/writer.py" | awk '{print $1}')"
[ "$cur" = "$(cat "$D/.fixture-writer-sha")" ] || fail "writer.py modified"
[ -f "$D/out/done.flag" ] || fail "done.flag missing"
grep -q '^done-by-writer-' "$D/out/done.flag" || fail "done.flag not written by writer"
st="$(cat "$D/out/.state" 2>/dev/null || true)"
[ "$st" = "completed" ] || fail "writer state: ${st:-none}"
exp_prog='stage-1
stage-2
stage-3
stage-4'
prog="$(cat "$D/out/progress.txt" 2>/dev/null || true)"
[ "$prog" = "$exp_prog" ] || fail "progress.txt not exactly 4 in-order stages"
verdict="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["verdict"])' "$D/out/result.json" 2>/dev/null)" || fail "result.json unreadable"
[[ "$verdict" =~ ^[0-9a-f]{12}$ ]] || fail "verdict not runtime-generated"
body_sha="$(shasum -a 256 "$D/out/result.json" | awk '{print $1}')"
rsha="$(cat "$D/out/.result-sha" 2>/dev/null || true)"
[ "$body_sha" = "$rsha" ] || fail "result.json not intact vs writer-recorded sha"
ans="$(tr -d '[:space:]' < "$D/answer.txt")"
[ "$ans" = "$verdict" ] || fail "answer mismatch: got '$ans' want '$verdict'"
printf '{"task":"T3","pass":true}\n' | tee "$D/.judge-verdict.json"
