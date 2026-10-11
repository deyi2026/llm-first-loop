#!/usr/bin/env bash
# ci_gate.sh — R9 CI 同款三件套门禁（一条命令本地复现）
#
# 链路: ruff → 测试环境声明门禁 → pyright → pytest -m tier0（预检快反馈）→ pytest --dist loadfile -n auto（全量）
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
#    但必须配 PYTHONPATH 指向本 worktree src，否则 editable 安装锚定旧主区 src → 静默测错代码树）
# 2) PYTHONPATH 前置本树 src——任何 worktree/旧主区运行 ci_gate，被测代码恒为本树。
PY="${PY:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  MAIN_WT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  [[ -x "$MAIN_WT/.venv/bin/python" ]] && PY="$MAIN_WT/.venv/bin/python"
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
MODE="${1:-full}"

echo "═══ [1/5] Ruff 全树静态诊断门禁（精确历史债 ratchet；修改文件零红）═══"
# 2026-10-08 CI contract: immutable gen201 baseline, every full-tree error visible.
# Fail on any new fingerprint/additional occurrence; all modified Python files
# must be 0-error even if the error predates this commit. A ledger edit itself
# is blocked unless independently reviewed under new governance. Never use
# arbitrary LFL_R9_BASE to reclassify already-known historical source debt.
"$PY" scripts/check_static_diagnostics.py --tool ruff

echo "═══ [2/5] 测试环境声明门禁（精确压缩预算断言必须声明 COMPACT_RATIO）═══"
# R817 教训固化（2026-09-09）：压缩阈值 = max_chars × COMPACT_RATIO（env 直读，
# history_budget_prep.py）。携带精确数值断言的测试若不声明环境依赖，
# ambient/.env 残留（load_env_file 写缺失键）可令其在零代码改动下翻红/漂移。
# 静态全树扫描，违例即阻断；规则与修复样例见 scripts/check_test_env_pins.py。
"$PY" scripts/check_test_env_pins.py

echo "═══ [3/5] Pyright 全树静态诊断门禁（精确历史债 ratchet；修改文件零红）═══"
"$PY" scripts/check_static_diagnostics.py --tool pyright

echo "═══ [4/5] 测试运行前置：隔离 HOME + 从候选源码构建 WebUI ═══"
# The MCP sandbox HOME is under /var/...; CatastrophicGuard intentionally
# blocks rm -rf /var/... even when the test calls that path "$HOME/data".
# Give pytest its own private, workspace-local, ignored HOME rather than
# weakening any safety assertion. The R9 PROBE worktree is removed by the
# wrapper; neither production HOME nor production data is touched.
CI_TEST_HOME="$ROOT/data/.ci-test-home"
mkdir -p "$CI_TEST_HOME"
chmod 700 "$CI_TEST_HOME"
export HOME="$CI_TEST_HOME"

# Playwright resolves its browser binary below HOME by default; since pytest
# has a deliberately isolated HOME, point it at the preinstalled *binary*
# cache for this OS account. Browser profiles still use pytest tmp_path.
# This is read-only reuse of installed test dependencies, not the user's
# live Chrome profile, and does not download anything from the network.
if [[ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ]]; then
  ACCOUNT_HOME="$("$PY" -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)')"
  for BROWSER_CACHE in "$ACCOUNT_HOME/Library/Caches/ms-playwright" "$ACCOUNT_HOME/.cache/ms-playwright"; do
    if [[ -d "$BROWSER_CACHE" ]]; then
      export PLAYWRIGHT_BROWSERS_PATH="$BROWSER_CACHE"
      break
    fi
  done
fi

# Git intentionally does not track webui/dist or webui/node_modules. The
# isolated R9 PROBE must BUILD assets from its own candidate sources:
# otherwise tests expecting /ui/v2/ fail with 404, unrelated to source.
# Reuse only installed dependency binaries from the canonical main worktree,
# not its dist (which could be stale or from a different commit). Never
# fetch dependencies from the network at a release qualification gate.
if [[ ! -d "$ROOT/webui/node_modules" ]]; then
  MAIN_WT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  if [[ ! -d "$MAIN_WT/webui/node_modules" ]]; then
    echo "❌ CI WebUI dependencies unavailable; preinstall pinned dependencies offline before gate" >&2
    exit 1
  fi
  ln -s "$MAIN_WT/webui/node_modules" "$ROOT/webui/node_modules"
fi
if ! (cd "$ROOT/webui" && npm run build) >/dev/null; then
  echo "❌ CI WebUI candidate build failed" >&2
  exit 1
fi
test -f "$ROOT/webui/dist/index.html" || { echo "❌ CI WebUI candidate dist missing" >&2; exit 1; }

echo "═══ [4/5] pytest tier0 预检（分钟级快反馈，非提交门禁）═══"
"$PY" -m pytest -m tier0 -q

if [[ "$MODE" == "--quick" ]]; then
  echo "── quick 模式止于预检：不构成提交门禁（R9-WF-01c）──"
  exit 0
fi

echo "═══ [5/5] pytest 全量门禁（xdist loadfile 并行；提交门禁恒为全量）═══"
# `-n auto` otherwise schedules 18 workers on this macOS host and can
# collide with another session's full-suite run, failing before pytest can
# even produce FAILED/ERROR node IDs. Bound concurrency; do NOT reduce
# collected test cases, turn off xdist, or reinterpret resource failures as
# passing tests. Operators may explicitly override the worker budget.
export PYTEST_XDIST_AUTO_NUM_WORKERS="${PYTEST_XDIST_AUTO_NUM_WORKERS:-4}"
echo "xdist worker budget=${PYTEST_XDIST_AUTO_NUM_WORKERS} (full test selection unchanged)"
GATE_OUT="$(mktemp /tmp/ci_gate_out.XXXXXX)"; GATE_SER="$(mktemp /tmp/ci_gate_ser.XXXXXX)"
if "$PY" -m pytest --dist loadfile -n auto -q >"$GATE_OUT" 2>&1; then
  echo "（xdist 全量绿）"
else
  # xdist 假红降级（D-B2-09，第四轮审查采纳）：红 → serial 单点复核——
  # serial 绿 = xdist worker 分布假红（呈现不阻断 + 登记观察）；仍红 = 真回归（阻断）。
  # 不登记永久 flaky 豁免（假红清单会烂账）；门禁语义 = serial 可复现红才阻断。
  # With set -euo pipefail, a zero-match grep would exit the gate before the
  # actual pytest error was surfaced. ERROR fixture/setup nodes matter just
  # as much as FAILED assertions; collect both without masking other failures.
  fail_files="$({ grep '^FAILED ' "$GATE_OUT" || true; grep '^ERROR ' "$GATE_OUT" || true; } \
    | sed -E 's/^(FAILED|ERROR) //' | cut -d: -f1 | sort -u)"
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

echo "✅ ci_gate 全链路通过（ruff + env-pin 声明门禁 + pyright + tier0 预检 + 全量门禁）"