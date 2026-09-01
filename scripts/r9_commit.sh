#!/usr/bin/env bash
# R9 提交包装入口（B2-P1-04 / R9-P1-03）：机检 → 门禁 → git commit
# 用法: bash scripts/r9_commit.sh "<commit message>"
#   message 可含多行（$'...' 传入）；等价性回执行 wire-fixtures: PASS 由提交者
#   跑 fixtures 对照后自附（refactor(r9) 前缀时机检强制）。
#
# 设计（§0.5 裁量）：不装 .git/hooks、不改 core.hooksPath——镜像区 .git 由外部
# 会话共享，强制 hook 会波及外部提交。机检以本脚本承载；外部混合层合流后再评估
# hook 化（EVO 待办）。
#
# 提交队列（B3-PREP-06）：多代理/多会话并行提交的唯一串行化点——锁住机检/门禁/
# 提交全段（write-tree 预检与 git commit 之间的 TOCTOU、ci_gate 读树与提交推进
# 错位经队列消除）。锁 = <git-common-dir>/r9-commit.lock（主区与各 worktree 共享
# 一把，跨 checkout 互斥）；排队语义 = 拿锁后若 HEAD 已被前移，新队头基线重跑
# 机检/门禁，暂存触碰面与前驱重叠即中止（stale 暂存基线防线）。锁超时
# R9_COMMIT_LOCK_TIMEOUT（默认 900s）+ trap 释放防死锁。
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

MSG="${1:?用法: bash scripts/r9_commit.sh \"<commit message>\"}"

# 暂存区须非空（防空提交/漏 add）
if git diff --cached --quiet; then
  echo "❌ 暂存区为空——先精确 git add 目标文件（B1 模式，隔离外部混合层）" >&2
  exit 1
fi

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

# [2/3] 门禁：ci_gate 全链路（恒全量口径）
# 外部红登记豁免（B3 豁免登记机制 / 裁决 2026-09-01 (b)+两闸）：
# registry = tests/guards/external_red_registry.json（guard(r9) 通道专管，规则④）。
# 失败项须与 registry 引号定界精确 token 匹配（grep -qF "\"<id>\""）方计豁免；
# 清单外任何红中止。两闸：①逐项登记含归因（registry _meta）；②B3-CLOSE-03
# 收口强制逐项销号复核——豁免不设永久遮罩。旧 EXTERNAL_EXEMPT 硬编码数组废止
# （D-07 已由守卫双口径收口 dbf340f；D-08 env flaky 不预防性豁免，复发按新证据登记）。
REGISTRY="tests/guards/external_red_registry.json"
GATE_LOG="$(mktemp /tmp/r9_gate.XXXXXX)"
if bash scripts/ci_gate.sh > "$GATE_LOG" 2>&1; then
  echo "✅ ci_gate 全链路 EXIT=0"
else
  # 空集防护（B3-PREP-06 自验实证缺陷）：非零退出但未达 [4/4] 测试步（ruff 快死/
  # PY 解析失败/早退）= 基建失败，不属任何豁免语义——零 FAILED 行的空集放行即漏洞
  if ! grep -q "═══ \[4/4\]" "$GATE_LOG"; then
    echo "❌ ci_gate 非零退出且未达 [4/4] 测试步——基建失败（非测试红），中止" >&2
    echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1
  fi
  collect_failed() { grep -oE "FAILED [^ ]+" "$GATE_LOG" | sed 's/^FAILED //'; true; }
  bad=0; n_ok=0
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    if [ -f "$REGISTRY" ] && grep -qF "\"$t\"" "$REGISTRY"; then
      n_ok=$((n_ok+1))
    else
      echo "❌ 门禁红（external_red_registry 清单外）: $t"; bad=1
    fi
  done < <(collect_failed)
  if [ "$bad" -eq 1 ]; then echo "── ci_gate 输出尾部 ──"; tail -20 "$GATE_LOG"; exit 1; fi
  echo "⚠️ ci_gate 非零退出：${n_ok} 项失败全部属 external_red_registry 登记项（外部演进配对面缺口；B3-CLOSE-03 强制销号复核）——放行提交"
fi

# [3/3] 提交（机检+门禁双绿后，安全扫描拦截）
# 安全扫描（--staged：暂存区敏感/私密/错误文件硬拦截；2026-08-16 机制沿用）
bash scripts/git_security_scan.sh
git commit -m "$MSG"
bash "$CHECK" HEAD
echo "✅ R9 提交完成（机检 + 门禁 + 提交三步全绿）"
