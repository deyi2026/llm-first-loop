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
  if [[ "$f" == "tests/unit/test_arch_guards.py" ]]; then
    $is_guard && continue
    # 例外④a（B5-W1-03 / D-B5-3）：refactor(r9) 触碰 test_arch_guards.py 须
    # 同时满足——body 含标记行 "guard-verified: ratchet-tighten"（提交者声明
    # 已在提交树口径跑守卫全绿）+ 守卫常量 _MIXIN_CAP 数值只降不升（棘轮方向
    # 机检；放松仍拦）。test_function_size_guard.py 不在例外内（guard-only 不变）。
    # 例外④a-2（B5-W2-01 / D-B5-5）：mixin-renames 通道——职责面迁出引发
    # Mixin 更名（_LifecycleMixin→_RunEntrypointMixin 类），棘轮测试增
    # _MIXIN_RENAMES 折算表。标记行 "guard-verified: mixin-renames" +
    # 机检：staged engine.py 基类名经 staged _MIXIN_RENAMES 折算后与 HEAD
    # 基类集**无净新增**（折算集−HEAD 集=∅ ⇒ "借更名夹带新基类"被守恒机检
    # 拦截；退役方向不受限）。与例外③ 同构：放松通道自带方向机检。
    if $is_refactor && grep -qE "^guard-verified: mixin-renames" <<<"$body"; then
      if python3 - <<'PY'
import re, subprocess, sys

def show(ref):
    r = subprocess.run(["git", "show", ref], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""

def bases(src):
    m = re.search(r"^class LoopEngine\(([^)]*)\):", src, re.M)
    return [b.strip() for b in m.group(1).split(",") if b.strip()] if m else None

head = bases(show("HEAD:src/llm_loop/core/loop/engine.py"))
staged = bases(show(":src/llm_loop/core/loop/engine.py"))
t = show(":tests/unit/test_arch_guards.py")
m = re.search(r"_MIXIN_RENAMES\s*=\s*\{([^}]*)\}", t, re.S)
renames = dict(re.findall(r"['\"]([A-Za-z_]\w*)['\"]\s*:\s*['\"]([A-Za-z_]\w*)['\"]", m.group(1))) if m else {}
if head is None or staged is None or not renames:
    print("④a-2 解析失败：基类列表或 _MIXIN_RENAMES 缺失")
    sys.exit(1)
def canon(names):
    # 双侧不动点折算：PROBE 检出态 HEAD=本提交（双侧同名）；提交后重跑态
    # HEAD=新世代（staged==HEAD，同上）；工作态 HEAD=旧世代（新名→旧名）
    prev = None
    cur = set(names)
    while prev != cur:
        prev = cur
        cur = {renames.get(n, n) for n in cur}
    return cur

extra = canon(staged) - canon(head)
if extra:
    print(f"④a-2 净新增基类（折算后）: {sorted(extra)}")
    sys.exit(1)
PY
      then
        continue
      fi
      fail "④" "例外④a mixin-renames 不满足：折算后净新增基类或 _MIXIN_RENAMES 缺失: ${f}"
    elif $is_refactor && grep -qE "^guard-verified: ratchet-tighten" <<<"$body"; then
      old_cap=$(git show "HEAD:tests/unit/test_arch_guards.py" 2>/dev/null | grep -oE "_MIXIN_CAP = [0-9]+" | grep -oE "[0-9]+" | head -1)
      new_cap=$(git show ":tests/unit/test_arch_guards.py" 2>/dev/null | grep -oE "_MIXIN_CAP = [0-9]+" | grep -oE "[0-9]+" | head -1)
      if [[ -n "$old_cap" && -n "$new_cap" && "$new_cap" -le "$old_cap" ]]; then
        continue
      fi
      fail "④" "例外④a 不满足：_MIXIN_CAP 非只降不升（HEAD=${old_cap:-无} → staged=${new_cap:-无}）: ${f}"
    else
      fail "④" "非 guard(r9) 前缀触碰守卫文件: ${f}（防篡改层 3，T3-C；例外④a = ratchet-tighten（CAP 只降）/ mixin-renames（守恒机检））"
    fi
  elif [[ "$f" == "tests/unit/test_function_size_guard.py" ]]; then
    $is_guard || fail "④" "非 guard(r9) 前缀触碰守卫文件: ${f}（防篡改层 3，T3-C）"
  fi
  if [[ "$f" == tests/guards/*.json ]]; then
    $is_guard && continue
    # 例外③（B5-W1-03 / D-B5-xx）：等价路径迁移通道——文件迁移/重命名场景下
    # 基线键路径随实现迁移（值严格不变）。标记行 "baseline-migration:
    # value-invariant" + 机检校验：function_lines+legacy 合并**值多重集相等**
    #（相等 ⇒ 无任何值篡改空间，防篡改不弱化；棘轮 HEAD 对比测试运行时兜底）
    # + known_cycles 纯收缩 + exemptions 零变更（_meta 说明性元数据豁免）。
    # 多重集不等 → 落回例外②（纯新增键）判定或拦截。
    if $is_refactor && grep -qE "^baseline-migration: value-invariant" <<<"$body"; then
      if ! python3 - "$COMMIT" "$f" <<'PY'
import json, subprocess, sys
from collections import Counter
c, rel = sys.argv[1], sys.argv[2]
def ver(ref):
    try:
        out = subprocess.run(["git", "show", f"{ref}:{rel}"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except Exception:
        return None
old, new = ver(c + "^"), ver(c)
if old is None or new is None:
    sys.exit(1)
vals_o = Counter(old.get("function_lines", {}).values()) + Counter(old.get("legacy_super_functions", {}).values())
vals_n = Counter(new.get("function_lines", {}).values()) + Counter(new.get("legacy_super_functions", {}).values())
oc, nc = old.get("known_cycles", []), new.get("known_cycles", [])
cycles_ok = set(nc) <= set(oc) and len(nc) <= len(oc)
exemptions_ok = old.get("exemptions") == new.get("exemptions")
sys.exit(0 if (vals_o == vals_n and cycles_ok and exemptions_ok) else 1)
PY
      then
        fail "④" "例外③ 不满足（等价迁移须值多重集相等 + known_cycles 纯收缩 + exemptions 零变更）: ${f}"
      fi
      continue
    fi
    # 唯一例外（B3-PREP-03 / tasks-b3 §0.5-1）：refactor(r9) 断环提交允许（且仅
    # 允许）同步缩减 known_cycles——数组纯收缩（新 ⊆ 旧且长度只减）+ 其余节零
    # 变更。对齐 cycle 守卫 stale 断言双向语义（环消失未清 known 即红 vs 规则④
    # 禁触守卫文件的死锁）；增长/改值/他节变更仍拦（防篡改层 3 不弱化）
    # 例外②（B4-C3-03 / D-B2-13 实证缺口）：refactor(r9) 新函数登记与实现同树
    # 场景——function_lines / legacy_super_functions 纯新增键（旧键值对零变更，
    # dict 视图子集判定）+ known_cycles 纯收缩 + 其余节零变更。旧键改值/删键
    # 仍须 guard(r9)（棘轮"值下降"归守卫测试与 guard 提交分管）；防篡改不弱化：
    # 任何旧键值篡改、节外变更依旧 FAIL。
    if $is_refactor && [[ "$f" == "tests/guards/function_size_baseline.json" ]]; then
      if ! python3 - "$COMMIT" "$f" <<'PY'
import json, subprocess, sys
c, rel = sys.argv[1], sys.argv[2]
def ver(ref):
    try:
        out = subprocess.run(["git", "show", f"{ref}:{rel}"], capture_output=True, text=True, check=True).stdout
        return json.loads(out)
    except Exception:
        return None
old, new = ver(c + "^"), ver(c)
if old is None or new is None:
    sys.exit(1)
oc, nc = old.get("known_cycles", []), new.get("known_cycles", [])
old.pop("known_cycles", None); new.pop("known_cycles", None)
cycles_ok = set(nc) <= set(oc) and len(nc) <= len(oc)
fl_o, fl_n = old.pop("function_lines", {}), new.pop("function_lines", {})
ls_o, ls_n = old.pop("legacy_super_functions", {}), new.pop("legacy_super_functions", {})
growth_ok = fl_o.items() <= fl_n.items() and ls_o.items() <= ls_n.items()
ok = (old == new) and cycles_ok and growth_ok
sys.exit(0 if ok else 1)
PY
      then
        fail "④" "基线例外不满足（known_cycles 须纯收缩；function_lines/legacy 须纯新增键且旧键值零变更；其余节零变更）: ${f}"
      fi
    else
      fail "④" "非 guard(r9) 前缀触碰守卫文件: ${f}（防篡改层 3，T3-C；唯一例外 = refactor(r9)+known_cycles 纯收缩）"
    fi
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
