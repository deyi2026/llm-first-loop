#!/usr/bin/env bash
# compose.sh T<n> A|B — 输出该 run 的完整任务正文（配置卡 + 任务卡）
set -euo pipefail
LAB="$(cd "$(dirname "$0")" && pwd)"
T="$1"; GRP="$2"
card="$LAB/config.card"; [ "$GRP" = "B" ] && card="$LAB/config-b.card"
cat "$card"; echo; echo "---"; echo; cat "$LAB/tasks/$T/task.md"
