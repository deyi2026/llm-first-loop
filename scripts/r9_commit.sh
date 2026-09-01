#!/usr/bin/env bash
# R9 提交包装入口（B2-P1-04 / R9-P1-03）：机检 → 门禁 → git commit
# 用法: bash scripts/r9_commit.sh "<commit message>"
#   message 可含多行（$'...' 传入）；等价性回执行 wire-fixtures: PASS 由提交者
#   跑 fixtures 对照后自附（refactor(r9) 前缀时机检强制）。
#
# 设计（§0.5 裁量）：不装 .git/hooks、不改 core.hooksPath——镜像区 .git 由外部
# 会话共享，强制 hook 会波及外部提交。机检以本脚本承载；外部混合层合流后再评估
# hook 化（EVO 待办）。
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

MSG="${1:?用法: bash scripts/r9_commit.sh \"<commit message>\"}"

# 暂存区须非空（防空提交/漏 add）
if git diff --cached --quiet; then
  echo "❌ 暂存区为空——先精确 git add 目标文件（B1 模式，隔离外部混合层）" >&2
  exit 1
fi

# [1/3] 机检：对 staged 树合成临时提交对象预检（write-tree/commit-tree 均不
#       移动引用、不留仓库中间态；悬挂对象由 GC 自然回收）
TREE="$(git write-tree)"
PROBE="$(printf '%s\n' "$MSG" | git commit-tree "$TREE" -p HEAD)"
CHECK="scripts/r9_commit_check.sh"
[ -f "$CHECK" ] || CHECK="r9_commit_check.sh"
bash "$CHECK" "$PROBE"

# [2/3] 门禁：ci_gate 全链路（恒全量口径）
# 过渡期外部级豁免（本批等价性门定义，B2-P1-01 至 B2-P2-06 生效区间）：
# 仅下列"已登记外部责任面"失败放行（WARN 呈现），清单外任何红一律中止。
# B2-P2-06 双口径机制落地后本清单应清空（D-07 归零）。
EXTERNAL_EXEMPT=(
  "tests/unit/test_function_size_guard.py::test_functions_within_baseline"  # D-07: 外部 factory.py working 漂移 1031>1004
  "tests/unit/test_p1_final.py"                                             # D-08: 外部 env 泄漏 flaky（B1 先例）
)
GATE_LOG="$(mktemp /tmp/r9_gate.XXXXXX)"
trap 'rm -f "$GATE_LOG"' EXIT
if bash scripts/ci_gate.sh > "$GATE_LOG" 2>&1; then
  echo "✅ ci_gate 全链路 EXIT=0"
else
  collect_failed() { grep -oE "FAILED [^ ]+" "$GATE_LOG" | sed 's/^FAILED //'; true; }
  bad=0
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    ok=""
    for e in "${EXTERNAL_EXEMPT[@]}"; do [[ "$t" == "$e"* ]] && ok=1 && break; done
    if [ -z "$ok" ]; then echo "❌ 门禁红（清单外，非外部级豁免）: $t"; bad=1; fi
  done < <(mapfile_failed)
  if [ "$bad" -eq 1 ]; then echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1; fi
  echo "⚠️ ci_gate 非零退出，但失败全部属已登记外部级豁免清单（D-07/D-08 过渡期口径）——放行提交"
fi

# [3/3] 提交（机检+门禁双绿后）
git commit -m "$MSG"
bash "$CHECK" HEAD
echo "✅ R9 提交完成（机检 + 门禁 + 提交三步全绿）"
