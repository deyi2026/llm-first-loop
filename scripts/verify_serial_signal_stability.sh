#!/usr/bin/env bash
# D3（2026-10-20）：终端信号类测试（serial_signal marker）稳定性验证。
# 用法：scripts/verify_serial_signal_stability.sh [--runs N]（默认 50）
# 任一次失败即退出非零并报告是第几次。
# 审查修订 P2-3：只收集目标单文件（tests/ 全量收集每轮徒增开销）；conftest 已改
# 函数级 SERIAL_SIGNAL_TESTS 清单，-m "serial_signal" 作为双保险保留。
# nightly job 的 timeout-minutes: 30 为整体兜底（每轮 4 用例远小于预算；
# 设计书"时限 2x"以 job 级 timeout 实现，不在脚本内做单轮计时）。
set -euo pipefail
RUNS=50
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs) RUNS="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
for i in $(seq 1 "$RUNS"); do
  echo "=== serial_signal run $i/$RUNS ==="
  if ! uv run python -m pytest tests/unit/test_terminal_cli.py -q -m "serial_signal"; then
    echo "serial_signal stability FAILED at run $i/$RUNS" >&2
    exit 1
  fi
done
echo "serial_signal stability OK: $RUNS/$RUNS"
