#!/usr/bin/env bash
# R9 commit 性质机检（design T2-C / D12 / R9-P1-03，B2-P1-04）
# 独立脚本形态，不装 git hook——.git 与外部会话共享，hook 会波及外部提交（§0.5 裁量）。
#
# 用法: bash scripts/r9_commit_check.sh [commit-ish]    # 默认 HEAD
# 也可对 commit-tree 合成的临时提交对象做预检（r9_commit.sh 提交前机检即此形态，
# 不移动引用、不留仓库中间态）。
#
# 五条判定（任一 FAIL 即退出码 1，信息指明违反的规则条目）：
#  ① 前缀白名单：subject 首行必须匹配
#     refactor(r9)/fix(r9)/feat(r9)/guard(r9)/chore(r9)/test(r9)/docs(r9) 或 switch(h<N>)
#  ② refactor(r9)：diff 文件集不得含行为面文件——src/llm_loop/cache_guard/**、
#     src/llm_loop/core/trace_leak/**、docs/r824/*.md（T2-C：结构/行为分提交）
#  ③ refactor(r9)：commit body 必含等价性回执标记行 "wire-fixtures: PASS"
#  ④ 非 guard(r9) 前缀触碰守卫文件（tests/unit/test_arch_guards.py、
#     tests/unit/test_function_size_guard.py、tests/guards/*.json）→ FAIL（防篡改层 3）
#  ⑤ 三开关默认值行变更（内容锚：LFL_TOOL_GUIDANCE / LFL_EVIDENCE_CAPSULE /
#     CACHE_GUARD_PERF_BLOCK，锚 registry.py:40 / evidence_enforce.py:40 / guard.py:56，
#     行号会漂移故按 env 键识别）必须 switch( 前缀（防无回执切换）
set -euo pipefail

COMMIT="${1:-HEAD}"
FAIL=0

subj="$(git log -1 --format=%s "$COMMIT")"
body="$(git log -1 --format=%b "$COMMIT")"
files=()
while IFS= read -r _f; do [ -n "$_f" ] && files+=("$_f"); done < <(git diff-tree --no-commit-id --name-only -r "$COMMIT" 2>/dev/null || true)

fail() { echo "❌ [r9_commit_check] 规则$1 FAIL @ ${COMMIT}: $2"; FAIL=1; }

# ── 规则①：前缀白名单（merge 提交只做本条——R9 线提交应全为线性） ──
if ! [[ "$subj" =~ ^((refactor|fix|feat|guard|chore|test|docs)\(r9\)|switch\(h[0-9]+\)): ]]; then
  fail "①" "前缀不在白名单: '$subj'"
  echo "   白名单: refactor(r9)/fix(r9)/feat(r9)/guard(r9)/chore(r9)/test(r9)/docs(r9)/switch(hN)"
fi

is_refactor=false; is_guard=false; is_switch=false
[[ "$subj" =~ ^refactor\(r9\): ]] && is_refactor=true
[[ "$subj" =~ ^guard\(r9\): ]] && is_guard=true
[[ "$subj" =~ ^switch\(h[0-9]+\): ]] && is_switch=true

# ── 规则②：refactor 不得触行为面文件 ──
if $is_refactor; then
  for f in ${files[@]+"${files[@]}"}; do  # 空 diff（纯消息）set -u 不崩（D-B2-05）
    if [[ "$f" == src/llm_loop/cache_guard/* || "$f" == src/llm_loop/core/trace_leak/* || "$f" == docs/r824/*.md ]]; then
      fail "②" "refactor(r9) 提交含行为面文件: ${f}（结构/行为分提交，T2-C）"
    fi
  done
  # ── 规则③：等价性回执标记 ──
  if ! grep -qE "^wire-fixtures: PASS" <<<"$body"; then
    fail "③" "refactor(r9) 提交缺等价性回执标记行 'wire-fixtures: PASS'（R9-P1-03b）"
  fi
fi

# ── 规则④：守卫文件前缀保护 ──
for f in ${files[@]+"${files[@]}"}; do  # 空 diff 提交（纯消息）set -u 不崩（D-B2-05：负例1 演练发现）
  if [[ "$f" == "tests/unit/test_arch_guards.py" || "$f" == "tests/unit/test_function_size_guard.py" || "$f" == tests/guards/*.json ]]; then
    $is_guard || fail "④" "非 guard(r9) 前缀触碰守卫文件: ${f}（防篡改层 3，T3-C）"
  fi
done

# ── 规则⑤：三开关默认值行内容锚 ──
if ! $is_switch; then
  changed="$(git diff-tree -p --no-commit-id "$COMMIT" -- \
    src/llm_loop/tools/registry.py src/llm_loop/tools/evidence_enforce.py \
    src/llm_loop/cache_guard/guard.py 2>/dev/null || true)"
  if grep -qE '^[+-].*(LFL_TOOL_GUIDANCE|LFL_EVIDENCE_CAPSULE|CACHE_GUARD_PERF_BLOCK)' <<<"$changed"; then
    fail "⑤" "三开关默认值行变更但无 switch(hN) 前缀（防无回执切换；锚 registry.py:40/evidence_enforce.py:40/guard.py:56）"
  fi
fi

if [ "$FAIL" -eq 0 ]; then
  echo "✅ [r9_commit_check] PASS @ ${COMMIT}: '$subj'（${#files[@]} files，五规则全过）"
fi
exit "$FAIL"
