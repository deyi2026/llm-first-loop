#!/usr/bin/env bash
# R9 提交包装入口（B2-P1-04 / R9-P1-03）：机检 → 门禁 → git commit
# 用法: bash scripts/r9_commit.sh "<commit message>"
#   message 可含多行（$'...' 传入）；等价性回执行 wire-fixtures: PASS 由提交者
#   跑 fixtures 对照后自附（refactor(r9) 前缀时机检强制）。
#
# 设计（§0.5 裁量）：本脚本不装 .git/hooks、不管理 core.hooksPath——机检以本脚本
# 承载，钩子统一由 scripts/install_security_hooks.sh 安装。历史：原裁量理由是
# 「镜像区 .git 由外部会话共享」，2026-11-10 镜像区取消（用户确认）后该前提消失，
# 钩子化改由安装脚本承担（EVO 待办落地）。
#
# 提交队列（B3-PREP-06）：多代理/多会话并行提交的唯一串行化点——锁住机检/门禁/
# 提交全段（write-tree 预检与 git commit 之间的 TOCTOU、ci_gate 读树与提交推进
# 错位经队列消除）。锁 = <git-common-dir>/r9-commit.lock（旧主区与各 worktree 共享
# 一把，跨 checkout 互斥）；排队语义 = 拿锁后若 HEAD 已被前移，新队头基线重跑
# 机检/门禁，暂存触碰面与前驱重叠即中止（stale 暂存基线防线）。锁超时
# R9_COMMIT_LOCK_TIMEOUT（默认 900s）+ trap 释放防死锁。
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source scripts/r9_probe_cleanup.sh

MSG="${1:?用法: bash scripts/r9_commit.sh \"<commit message>\"}"

# 暂存区须非空（防空提交/漏 add）
if git diff --cached --quiet; then
  echo "❌ 暂存区为空——先精确 git add 目标文件（B1 模式，隔离外部混合层）" >&2
  exit 1
fi

# ── [0a] 暂存区白名单（R9_STAGED_ALLOW）：隔离他人暂存残留 ──
# 背景（2026-11-10 事故）：本脚本最后是裸 `git commit`，提交的是**整个索引**。
# 上文「先精确 git add」只是流程约定，没有任何机制检测索引里是否多了不属于本次
# 的条目——他人 add 后离场留下的 staged 项会被静默混进本次提交（事故现场：2 个
# 他人 staged 回执混入）。设 R9_STAGED_ALLOW 后，索引中出现名单外条目即拒绝。
# 格式：每行一个路径，与 `git diff --cached --name-only` 输出一致；空行忽略。
# 未设该变量 = 行为与旧版完全一致（不改变他人调用姿势）。
if [ -n "${R9_STAGED_ALLOW:-}" ]; then
  ALLOW_LIST="$(mktemp /tmp/r9allow.XXXXXX)"
  printf '%s\n' "$R9_STAGED_ALLOW" | sed '/^[[:space:]]*$/d' | sort -u > "$ALLOW_LIST"
  UNEXPECTED="$(git diff --cached --name-only | sort -u | comm -23 - "$ALLOW_LIST")"
  rm -f "$ALLOW_LIST"
  if [ -n "$UNEXPECTED" ]; then
    echo "❌ 暂存区含 R9_STAGED_ALLOW 白名单外条目——拒绝提交（可能混入他人暂存残留）：" >&2
    printf '%s\n' "$UNEXPECTED" | sed 's/^/   /' >&2
    echo "   处置: 把这些条目移出暂存区（git restore --staged <path>），或加入 R9_STAGED_ALLOW 后重试" >&2
    exit 1
  fi
fi

# ── [0b] 钩子执行位守卫（动作层）──
# git 对「没有执行位的钩子」是静默跳过：不报错、不提示，钩子等于不存在。
# tests/unit/test_githooks_exec_bit.py 覆盖同一不变量，但只在被跑时生效；
# 本检查在**每次提交路径**上生效——否则钩子丢执行位后，pre-commit 里的
# 安全扫描（规则 1-6）与 pre-push 闸全部静默失效。
# 只校验索引模式：工作区 chmod 不随 clone 传播，索引 100755 才是历史事实。
for _hook in .githooks/pre-commit .githooks/pre-push; do
  [ -e "$_hook" ] || continue
  _hook_mode="$(git ls-files -s -- "$_hook" 2>/dev/null | awk '{print $1}')"
  if [ "$_hook_mode" != "100755" ]; then
    echo "❌ 钩子索引模式非 100755（${_hook}: ${_hook_mode:-未跟踪}）——git 会静默跳过该钩子，拒绝提交" >&2
    echo "   修复: chmod +x ${_hook} && git add ${_hook}" >&2
    exit 1
  fi
done

# ── [0] 提交队列锁（B3-PREP-06，先于机检/门禁/提交全段）──
# 兜底链（沿 1f0c6e7 PY 回落链设计语言）：flock 二进制（Linux/CI）→ python fcntl
# （macOS 无 flock；coproc 持锁 holder，EOF/kill/父亡孤儿自释三路释放）
GATE_LOG=""
LOCK_HOLDER_PID=""
LOCK_FILE="$(git rev-parse --path-format=absolute --git-common-dir)/r9-commit.lock"
LOCK_TIMEOUT="${R9_COMMIT_LOCK_TIMEOUT:-900}"
BASE_HEAD="$(git rev-parse HEAD)"
LOCK_PROG='import fcntl, os, sys, time
lockfile, timeout = sys.argv[1], float(sys.argv[2])
f = open(lockfile, "a+")
deadline = time.monotonic() + timeout
while True:
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
    except OSError:
        if time.monotonic() >= deadline:
            print("TIMEOUT", flush=True); sys.exit(1)
        time.sleep(0.2)
print("ACQUIRED", flush=True)
ppid0 = os.getppid()
while os.getppid() == ppid0:
    time.sleep(0.2)'
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -w "$LOCK_TIMEOUT" 9; then
    echo "❌ 提交队列锁等待超时（${LOCK_TIMEOUT}s）——排查持锁进程；确认无残留后可删 ${LOCK_FILE}" >&2
    exit 1
  fi
  LOCK_MODE="flock(fd9)"
else
  PY_BIN="$(command -v python3 || true)"
  [ -n "$PY_BIN" ] || { echo "❌ 无 flock 且无 python3——锁兜底链不可用" >&2; exit 1; }
  # bash 3.2 兼容（macOS 无 coproc）：ACK 文件轮询 + holder 孤儿再父自释
  # （getppid 漂移 = 父进程已亡 → 内核级释放；trap kill 为正常路径显式释放）
  LOCK_TMP="$(mktemp -d /tmp/r9lock.XXXXXX)"
  ACK="$LOCK_TMP/ack"
  "$PY_BIN" -c "$LOCK_PROG" "$LOCK_FILE" "$LOCK_TIMEOUT" > "$ACK" 2>&1 &
  LOCK_HOLDER_PID=$!
  LOCK_OK=""
  while [ $SECONDS -lt $((LOCK_TIMEOUT + 5)) ]; do
    if grep -q '^ACQUIRED$' "$ACK" 2>/dev/null; then LOCK_OK=1; break; fi
    if grep -q '^TIMEOUT$' "$ACK" 2>/dev/null; then break; fi
    kill -0 "$LOCK_HOLDER_PID" 2>/dev/null || { sleep 0.3; grep -q '^ACQUIRED$' "$ACK" 2>/dev/null && LOCK_OK=1; break; }
    sleep 0.2
  done
  if [ -z "$LOCK_OK" ]; then
    grep -q '^TIMEOUT$' "$ACK" 2>/dev/null && echo "❌ 提交队列锁等待超时（${LOCK_TIMEOUT}s）——排查持锁进程；确认无残留后可删 ${LOCK_FILE}" >&2 \
      || echo "❌ 锁 holder 异常退出（未获锁）" >&2
    kill "$LOCK_HOLDER_PID" 2>/dev/null || true
    rm -rf "$LOCK_TMP"
    exit 1
  fi
  rm -rf "$LOCK_TMP"
  LOCK_MODE="fcntl(pid=${LOCK_HOLDER_PID})"
fi
echo "🔒 提交队列锁已获取（$(date +%H:%M:%S) · ${LOCK_MODE} @ ${LOCK_FILE}）"
trap 'if [ -n "${LOCK_HOLDER_PID:-}" ]; then kill "$LOCK_HOLDER_PID" 2>/dev/null || true; fi; flock -u 9 2>/dev/null || true; if [ -n "${GATE_LOG:-}" ]; then rm -f "$GATE_LOG"; fi' EXIT

# 队头 ff 再检（排队语义）：等待期间他人已提交（HEAD ≠ 取锁前观测基线）→ 在新
# 队头基线重跑机检/门禁；暂存触碰面与前驱提交重叠 = stale 暂存基线 → 中止人工处置
HEAD_NOW="$(git rev-parse HEAD)"
if [ "$HEAD_NOW" != "$BASE_HEAD" ]; then
  echo "⏩ 队头已前移（$(git rev-parse --short "$BASE_HEAD") → $(git rev-parse --short HEAD)），排队语义生效：新基线重跑机检/门禁"
  if comm -12 <(git diff --name-only "$BASE_HEAD" HEAD | sort) <(git diff --cached --name-only | sort) | grep -q .; then
    OVERLAP="$(comm -12 <(git diff --name-only "$BASE_HEAD" HEAD | sort) <(git diff --cached --name-only | sort) | tr '\n' ' ')"
    echo "❌ 暂存触碰面与前驱提交重叠（${OVERLAP}）——stale 暂存基线，中止并人工 re-stage" >&2
    exit 1
  fi
fi

# [1/3] 机检：对 staged 树合成临时提交对象预检（write-tree/commit-tree 均不
#       移动引用、不留仓库中间态；悬挂对象由 GC 自然回收）
TREE="$(git write-tree)"
PROBE="$(printf '%s\n' "$MSG" | git commit-tree "$TREE" -p HEAD)"
CHECK="scripts/r9_commit_check.sh"
[ -f "$CHECK" ] || CHECK="r9_commit_check.sh"
bash "$CHECK" "$PROBE"

# [2/3] 门禁：ci_gate 全链路（Gate 0 项1+3：PROBE 隔离检出执行 + 完整收集）
# Gate 0 勘误（b4-execution-log §23.5）：旧口径 ci_gate 在调用者 working tree 运行，
# 门禁没有执行提交态——同一 PROBE 随外部 M/fixture 状态出现不同红集。改造：
# ① PROBE 树隔离检出（临时 detached worktree），ruff/pyright/pytest 全部读取 PROBE 内容；
# ② fixture 按 tests/guards/fixture_manifest.json 校验在位（缺失 = 基建失败，Gate 0 项2）；
# ③ collect_failed 抓 FAILED+ERROR（含 collection/setup error）；非零退出但失败集为空
#    = 未知失败形态（xdist worker crash 等）→ 拒绝放行（不留空集漏洞）。
# 豁免机制不变：registry = tests/guards/external_red_registry.json（PROBE 态即提交态，
# registry 随提交原子生效）；node id 引号定界精确匹配；清单外任何红中止。
# Gate 0 日志归档：GATE_LOG 不再即弃，归档 /tmp/r9_gate_last.log（失败指纹审计面）。
REGISTRY="tests/guards/external_red_registry.json"
FIXTURE_MANIFEST="tests/guards/fixture_manifest.json"
GATE_LOG="$(mktemp /tmp/r9_gate.XXXXXX)"
PROBE_WT="$(mktemp -d /tmp/r9probe.XXXXXX)"
# Git lists physical paths (e.g. /private/tmp on macOS), not symlink aliases.
PROBE_WT="$(cd "$PROBE_WT" && pwd -P)"
r9_cleanup_exit() {
  local result="$1"
  if [ -n "${LOCK_HOLDER_PID:-}" ]; then kill "$LOCK_HOLDER_PID" 2>/dev/null || true; fi
  flock -u 9 2>/dev/null || true
  if [ -n "${PROBE_WT:-}" ]; then
    if ! r9_cleanup_probe "$PROBE_WT"; then
      if [ "$result" -eq 0 ]; then result=1; fi
    fi
  fi
  if [ -n "${GATE_LOG:-}" ]; then
    if ! cp "$GATE_LOG" "${R9_GATE_RECEIPT_FILE:-/tmp/r9_gate_last.log}"; then
      echo "R9 gate receipt archive failed: $GATE_LOG" >&2
      if [ "$result" -eq 0 ]; then result=1; fi
    fi
    rm -f "$GATE_LOG" || true
  fi
  exit "$result"
}
trap 'r9_cleanup_exit $?' EXIT
git worktree add --detach "$PROBE_WT" "$PROBE" > /dev/null 2>&1 || { echo "❌ PROBE 隔离检出失败（$PROBE_WT）" >&2; exit 1; }
# Gate 0 项2：fixture 版本化校验（PROBE 树内 manifest 对本体 hash 逐项校验）
if [ -f "$PROBE_WT/$FIXTURE_MANIFEST" ]; then
  if ! python3 - "$PROBE_WT" "$FIXTURE_MANIFEST" << 'PYEOF'
import hashlib, json, sys
wt, mf = sys.argv[1], sys.argv[2]
for e in json.load(open(f"{wt}/{mf}"))["files"]:
    b = open(f"{wt}/{e['path']}", "rb").read()
    assert hashlib.sha256(b).hexdigest() == e["sha256"], f"hash mismatch: {e['path']}"
print("fixture manifest OK")
PYEOF
  then
    echo "❌ fixture manifest 校验失败（缺失或 hash 不符）——Gate 0 项2 防线" >&2
    exit 1
  fi
fi
GATE_EXIT=0
(cd "$PROBE_WT" && bash scripts/ci_gate.sh) > "$GATE_LOG" 2>&1 || GATE_EXIT=$?
# PY 解析：PROBE 检出无 .venv → ci_gate 内部回落链取主 worktree .venv；PYTHONPATH 已由 ci_gate 前置 $ROOT/src（=PROBE 树）

if [ "$GATE_EXIT" -eq 0 ]; then
  echo "✅ ci_gate 全链路 EXIT=0（PROBE 隔离态，PROBE=$(git rev-parse --short "$PROBE")）"
else
  # Gate 0 项3-空集防护（升级）：未达 [5/5] 全量测试步 = 基建失败；已达但失败集为空 = 未知
  # 失败形态（xdist worker crash / collection 中断无节点行）——两者都拒绝放行。
  # 2026-09-10：ci_gate 步进格式已是 5 步（[2/5]..[5/5]，仅 [1/4] ruff 残留旧标号），
  # 探测标记从旧 [4/4] 对准最终测试步 [5/5]——旧标记永不匹配导致"基建失败"误判中止。
  if ! grep -q "═══ \[5/5\]" "$GATE_LOG"; then
    echo "❌ ci_gate 非零退出且未达 [5/5] 测试步——基建失败（非测试红），中止" >&2
    echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1
  fi
  # 完整收集：FAILED + ERROR（collection/setup error 节点行）；node id 去重排序。
  # 各 grep 兜底 || true：pipefail 下零匹配（EXIT 1）会静默炸整脚本（三跑 trace 实证）
  collect_failed() {
    { grep -oE "FAILED [^ ]+" "$GATE_LOG" || true; grep -oE "ERROR [^ ]+" "$GATE_LOG" || true; } \
      | awk '{print $2}' | sort -u
    true
  }
  collect_failed > "$GATE_LOG.fails"
  if [ ! -s "$GATE_LOG.fails" ]; then
    echo "❌ ci_gate 非零退出（EXIT=$GATE_EXIT）但失败集为空——未知失败形态，拒绝放行（Gate 0 项3）" >&2
    echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1
  fi
  # registry 匹配：PROBE 态 registry（提交态随提交原子生效）
  bad=0; n_ok=0
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    if grep -qF "\"$t\"" "$PROBE_WT/$REGISTRY" 2>/dev/null; then
      n_ok=$((n_ok+1))
    else
      echo "❌ 门禁红（external_red_registry 清单外）: $t"; bad=1
    fi
  done < "$GATE_LOG.fails"
  if [ "$bad" -eq 1 ]; then echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1; fi
  echo "⚠️ ci_gate 非零退出（PROBE 隔离态）：${n_ok} 项失败全部属 external_red_registry 登记项（临时 allowlist；销号复核沿 C 裁决逐批）——放行提交"
fi

# [3/3] 提交（机检+门禁双绿后，安全扫描拦截）
# 安全扫描（--staged：暂存区敏感/私密/错误文件硬拦截；2026-08-16 机制沿用）
bash scripts/git_security_scan.sh
git commit -m "$MSG"
bash "$CHECK" HEAD
echo "✅ R9 提交完成（机检 + 门禁 + 提交三步全绿）"
