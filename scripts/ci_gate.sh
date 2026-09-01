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
ROOT="$(pwd)"

# 并行底座自足化（R9-B3 前置/用户原则：阻碍并行执行的环境陷阱要修）：
# 1) PY 解析——worktree 自带 .venv 优先；无则回落主检出区 .venv（worktree 共享 venv 可用，
#    但必须配 PYTHONPATH 指向本 worktree src，否则 editable 安装锚定主区 src → 静默测错代码树）
# 2) PYTHONPATH 前置本树 src——任何 worktree/主区运行 ci_gate，被测代码恒为本树。
PY="${PY:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  MAIN_WT="$(git worktree list --porcelain | head -1 | cut -d' ' -f2)"
  [[ -x "$MAIN_WT/.venv/bin/python" ]] && PY="$MAIN_WT/.venv/bin/python"
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
MODE="${1:-full}"

echo "═══ [1/4] ruff 全量门禁（全量阻断 + 外部层呈现）═══"
# 口径（R9-B2-P1-05 升级）：`ruff check src tests scripts` 退出码【阻断】——
# R9 拥有面零违规（B1 时点存量 113 处已于 ae6faca 清偿：R9 面 94 修复 +
# 外部层只读避让；wrapper 提交窗口内 staged==working，工作区口径即提交口径）。
# 外部混合层 M/untracked 文件（三分表②/③区）的违规属外部责任面——沿 D-07
# 区分逻辑：外部文件 = 当前脏 ∧ 未被 R9 提交链触碰（R9_BASE..HEAD）；R9 拥有
# 面（R9 提交过的文件——含其编辑窗口——及一切干净文件）违规即阻断。R9 编辑
# 窗口内 staged==working，工作区口径即提交口径（负例实测：R9 文件注入违规
# 必须阻断，不得因"变脏"误判外部级）。
# B3 口径修正（并行底座）：阻断面 = R9 提交链触碰过的文件（绝对口径，与
# porcelain 无关）——worktree 干净检出下"非外部=R9 拥有面"的旧相对判定会把
# 外部历史遗留违规（HEAD 上的 I001 等）全量误判阻断（parity 实测 0.31s 即挂）。
# R9 编辑窗口语义不变：R9 文件无论 staged/working 均在 diff 集 → 违规阻断。
R9_BASE="${LFL_R9_BASE:-eac9b2a}"
_r9_py="$(git diff --name-only --diff-filter=d "${R9_BASE}..HEAD" -- '*.py' | sort -u || true)"
_ext_py="$(git status --porcelain | awk '$1=="M"||$1=="??"{print $2}' | grep '\.py$' | grep -vxFf <(printf '%s\n' "$_r9_py") || true)"
_ruff_out="$("$PY" -m ruff check src tests scripts --output-format=concise 2>&1 || true)"
_vfiles="$(printf '%s\n' "$_ruff_out" | grep -oE '^[^:]+\.py' | sort -u || true)"
if [ -n "$_vfiles" ]; then
  _blocked="$(printf '%s\n' "$_vfiles" | grep -xFf <(printf '%s\n' "$_r9_py") || true)"
  printf '%s\n' "$_ruff_out" | grep -E '^[^:]+\.py:[0-9]+' | while IFS= read -r ln; do
    _f="$(printf '%s' "$ln" | cut -d: -f1)"
    if printf '%s\n' "$_ext_py" | grep -qxF "$_f"; then
      echo "⚠️  外部级（呈现不阻断）: $ln"
    fi
  done
  if [ -n "$_blocked" ]; then
    echo "❌ ruff 违规（R9 拥有面，阻断）:"
    printf '%s\n' "$_ruff_out" | grep -E '^[^:]+\.py:[0-9]+' | while IFS= read -r ln; do
      _f="$(printf '%s' "$ln" | cut -d: -f1)"
      printf '%s\n' "$_blocked" | grep -qxF "$_f" && echo "$ln"
    done
    exit 1
  fi
  echo "（R9 拥有面零违规；上述外部级项属三分表②/③区责任面，外部合流时清偿）"
else
  echo "（全量零违规——src tests scripts 干净）"
fi

echo "═══ [2/4] pyright（类型检查 src）═══"
"$PY" -m pyright

echo "═══ [3/4] pytest tier0 预检（分钟级快反馈，非提交门禁）═══"
"$PY" -m pytest -m tier0 -q

if [[ "$MODE" == "--quick" ]]; then
  echo "── quick 模式止于预检：不构成提交门禁（R9-WF-01c）──"
  exit 0
fi

echo "═══ [4/4] pytest 全量门禁（xdist loadfile 并行；提交门禁恒为全量）═══"
GATE_OUT="$(mktemp)"; GATE_SER="$(mktemp)"
if "$PY" -m pytest --dist loadfile -n auto -q >"$GATE_OUT" 2>&1; then
  echo "（xdist 全量绿）"
else
  # xdist 假红降级（D-B2-09，第四轮审查采纳）：红 → serial 单点复核——
  # serial 绿 = xdist worker 分布假红（呈现不阻断 + 登记观察）；仍红 = 真回归（阻断）。
  # 不登记永久 flaky 豁免（假红清单会烂账）；门禁语义 = serial 可复现红才阻断。
  fail_files="$(grep '^FAILED' "$GATE_OUT" | sed 's/^FAILED //' | cut -d: -f1 | sort -u)"
  if [ -z "$fail_files" ]; then
    cat "$GATE_OUT"; rm -f "$GATE_OUT" "$GATE_SER"; exit 1
  fi
  n_files="$(echo "$fail_files" | wc -l | tr -d ' ')"
  echo "── xdist 红（${n_files} 文件）→ serial 单点复核（D-B2-09 降级流程）──"
  if "$PY" -m pytest $fail_files -q >"$GATE_SER" 2>&1; then  # shellcheck disable=SC2086
    echo "⚠️ serial 复核绿 = xdist 分布假红（不阻断；文件清单如下，登记观察）"
    echo "$fail_files"
  else
    cat "$GATE_SER"; rm -f "$GATE_OUT" "$GATE_SER"; exit 1
  fi
fi
rm -f "$GATE_OUT" "$GATE_SER"

# Phase 2 接线（B2-P2-08）：守卫 WARN 汇总呈现（不阻断；FAIL 用例已在 [4/4] 全量天然覆盖）
"$PY" -m pytest tests/unit/test_arch_guards.py -m guard_report -q

echo "✅ ci_gate 全链路通过（ruff + pyright + tier0 预检 + 全量门禁）"