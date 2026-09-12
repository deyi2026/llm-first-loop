#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D/files"
i=1
while [ "$i" -le 40 ]; do
  printf 'payload-%02d\n' "$i" > "$D/files/old_$(printf '%02d' "$i").txt"
  i=$((i+1))
done
(cd "$D/files" && cat $(ls old_*.txt | sort) | shasum -a 256 | awk '{print $1}') > "$D/.fixture-concat-sha"
