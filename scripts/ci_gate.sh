#!/usr/bin/env bash
# ci_gate.sh — R9 CI 同款三件套门禁（一条命令本地复现）
#
# 链路: ruff → pyright → pytest -m tier0（预检快反馈）→ pytest --dist loadfile -n auto（全量）
#
# ⚠️ 门禁不降级（R9-WF-01c 常驻原则）: tier0 仅是开发回路预检（分钟级反馈），
#    提交门禁恒为【全量】——本脚本最后一步永远跑全量用例，任何"分层=可以少跑"
#    的解读都被本脚本的结构否定。
#
# 依赖: uv sync --frozen --extra dev（R9-IMM-03 一键安装三件套）
#
# 用法:
#   bash scripts/ci_gate.sh            # 全链路（预检 + 全量）
#   bash scripts/ci_gate.sh --quick    # 仅预检（tier0，开发回路；不构成提交门禁）
#
# Phase 2 接线占位（本批不实现）:
#   - 守卫 WARN 汇总: pytest tests/unit/test_arch_guards.py -m guard-report
#     （test_arch_guards.py 属 R9 Phase 2 守卫重建产物，本批未收编；接线时追加在
#      全量步骤之后、作为 WARN 汇总呈现，不阻断 CI）

set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
MODE="${1:-full}"

echo "═══ [1/4] ruff（R9 提交面零违规检查）═══"
# 口径（R9-B1）：对 R9 批次提交（eac9b2a..HEAD）涉及 .py 文件零违规【阻断】。
# 全量口径现状：113 处存量历史遗留（build.py/GATES 等，51 文件非外部层）+ 外部
# 混合层 dirty 中间态——存量清偿属 Phase 1「main 全绿门禁」范围，届时本步骤
# 升级为全量阻断。当前附全量统计（信息呈现，不阻断）。
GATE_BASE="${LFL_GATE_BASE:-eac9b2a}"
_ruff_files="$(git diff --name-only --diff-filter=d "${GATE_BASE}..HEAD" -- '*.py' | sort -u)"
if [[ -n "$_ruff_files" ]]; then
  # shellcheck disable=SC2086
  "$PY" -m ruff check $_ruff_files
else
  echo "（R9 提交面无 .py 变更）"
fi
echo "── ruff 全量统计（存量基线 113，信息呈现不阻断）──"
"$PY" -m ruff check src tests scripts 2>&1 | tail -1 || true

echo "═══ [2/4] pyright（类型检查 src）═══"
"$PY" -m pyright

echo "═══ [3/4] pytest tier0 预检（分钟级快反馈，非提交门禁）═══"
"$PY" -m pytest -m tier0 -q

if [[ "$MODE" == "--quick" ]]; then
  echo "── quick 模式止于预检：不构成提交门禁（R9-WF-01c）──"
  exit 0
fi

echo "═══ [4/4] pytest 全量门禁（xdist loadfile 并行；提交门禁恒为全量）═══"
"$PY" -m pytest --dist loadfile -n auto -q

# Phase 2 接线占位：守卫 WARN 汇总（test_arch_guards.py 收编后启用）
# "$PY" -m pytest tests/unit/test_arch_guards.py -m guard-report

echo "✅ ci_gate 全链路通过（ruff + pyright + tier0 预检 + 全量门禁）"