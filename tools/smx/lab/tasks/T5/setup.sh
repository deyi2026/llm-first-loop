#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D/src"
i=1
while [ "$i" -le 10 ]; do
  printf 'key-%02d,value=%d\n' "$i" $((i*3)) >> "$D/src/entries.txt"
  i=$((i+1))
done
shasum -a 256 "$D/src/entries.txt" | awk '{print $1}' > "$D/.fixture-entries-sha"
