#!/usr/bin/env bash
# R9 提交包装入口（B2-P1-04 / R9-P1-03）：机检 → 门禁 → git commit
# 用法: bash scripts/r9_commit.sh "<commit message>"
#   message 可含多行（$'...' 传入）；等价性回执行 wire-fixtures: PASS 由提交者
#   跑 fixtures 对照后自附（refactor(r9) 前缀时机检强制）。
#   提交前无条件打印暂存清单（供目视核对"本次到底提交什么"）；可选环境变量
#   R9_STAGED_ALLOW（每行一个路径）声明本次允许的条目——索引中出现名单外条目
#   即拒绝，用于隔离他人暂存残留。
#
# 设计（§0.5 裁量）：本脚本不装 .git/hooks、不管理 core.hooksPath——机检以本脚本
# 承载，钩子统一由 scripts/install_security_hooks.sh 安装。历史：原裁量理由是
# 「镜像区 .git 由外部会话共享」，2026-11-10 镜像区取消（用户确认）后该前提消失，
# 钩子化改由安装脚本承担（EVO 待办落地）。
#
# Each checkout serializes its own candidate preparation and test run. The
# shared repository lock covers only the final exact-tree/HEAD CAS and commit.
# Older wrappers holding the common lock remain compatible; --dev retains the
# original full common-lock contract for its independent Host authorization.
set -euo pipefail
# A commit wrapper must reject inherited repository redirection, not silently
# clear it: the caller might have intended a different index or object store.
# Check before any repository lookup, lock, staging inspection or mutation.
_git_local_vars="$(git rev-parse --local-env-vars)"
for _git_var in $_git_local_vars GIT_NAMESPACE GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM; do
  if [[ -n "${!_git_var:-}" ]]; then
    echo "[GIT_WORKSPACE_ENVIRONMENT_ERROR] inherited Git repository variable: $_git_var; unsafe Git/shell environment: $_git_var; retry from the intended checkout with a clean Git environment" >&2
    exit 78
  fi
done
if [[ "$(git config --local --bool --get core.bare 2>/dev/null || true)" == true ]]; then
  echo "[GIT_WORKSPACE_ENVIRONMENT_ERROR] shared core.bare=true; preserve config and investigate its writer before retrying" >&2
  exit 78
fi
cd "$(git rev-parse --show-toplevel)"
source scripts/r9_probe_cleanup.sh

# REQ-FLOW-004: no env var can enable --dev. The installed independent Host
# authority is root-owned, separately activated and one-use; absent => deny.
DEV_MODE=0
DEV_GOAL=""
DEV_REQ=""
DEV_BASE=""
DEV_DESIGN=""
DEV_GRANT=""
MSG=""
HOST_DEV_AUTH="/Library/Application Support/LFL-HostIssuer/bin/dev_commit_host_authority.py"
if [[ "${1:-}" == --dev ]]; then
  DEV_MODE=1
  shift
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --goal|--req|--base|--design|--grant-id)
        [[ "$#" -ge 2 ]] || { echo "[DEV_COMMIT_DISABLED] missing option value" >&2; exit 78; }
        case "$1" in
          --goal) DEV_GOAL="$2";;
          --req) DEV_REQ="$2";;
          --base) DEV_BASE="$2";;
          --design) DEV_DESIGN="$2";;
          --grant-id) DEV_GRANT="$2";;
        esac
        shift 2;;
      --) shift; break;;
      -*) echo "[DEV_COMMIT_DISABLED] unsupported dev argument: $1" >&2; exit 78;;
      *) [[ -z "$MSG" ]] || { echo "[DEV_COMMIT_DISABLED] multiple messages" >&2; exit 78; }
         MSG="$1"; shift;;
    esac
  done
  [[ "$#" -eq 0 && -n "$MSG" && -n "$DEV_GOAL" && -n "$DEV_REQ" &&
     -n "$DEV_BASE" && -n "$DEV_DESIGN" && -n "$DEV_GRANT" ]] ||
    { echo "[DEV_COMMIT_DISABLED] incomplete dev request" >&2; exit 78; }
  [[ "$DEV_DESIGN" == docs/design/*.md && "$DEV_DESIGN" != *..* ]] ||
    { echo "[DEV_COMMIT_DISABLED] design path invalid" >&2; exit 78; }
  [[ -f "$HOST_DEV_AUTH" && -x /usr/bin/sudo && -x /usr/bin/python3 ]] ||
    { echo "[DEV_COMMIT_DISABLED] independent Host authority not installed" >&2; exit 78; }
  [[ -n "${R9_STAGED_ALLOW:-}" ]] ||
    { echo "[DEV_COMMIT_DISABLED] R9_STAGED_ALLOW is mandatory" >&2; exit 78; }
  for _unsafe_git_var in GIT_DIR GIT_COMMON_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_NAMESPACE GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS BASH_ENV; do
    [[ -z "${!_unsafe_git_var:-}" ]] ||
      { echo "[DEV_COMMIT_DISABLED] unsafe Git/shell environment: $_unsafe_git_var" >&2; exit 78; }
  done
else
  for _r9_arg in "$@"; do
    if [[ "$_r9_arg" == --dev || "$_r9_arg" == --dev=* ]]; then
      echo "[DEV_COMMIT_DISABLED] dev mode must be explicit and Host-authorized" >&2
      exit 78
    fi
  done
  MSG="${1:?用法: bash scripts/r9_commit.sh \"<commit message>\"}"
fi

# 暂存区须非空（防空提交/漏 add）
if git diff --cached --quiet; then
  echo "❌ 暂存区为空——先精确 git add 目标文件（B1 模式，隔离外部混合层）" >&2
  exit 1
fi

# ── [0] 暂存清单（无条件打印；不阻断、不改变提交内容）──
# 事故教训（详见 [0a]）：本脚本最后是裸 git commit，提交的是整个索引。
# R9_STAGED_ALLOW 只在显式传值时拦截；未传值的调用方靠这几行目视核对，
# 让"混入他人暂存残留"在提交瞬间可见，而不是事后在历史里发现。
STAGED_LIST="$(git -c core.quotePath=false diff --cached --name-only)"
echo "── 暂存区：本次提交将包含 $(printf '%s\n' "$STAGED_LIST" | wc -l | tr -d ' ') 项 ──" >&2
printf '%s\n' "$STAGED_LIST" | sed 's/^/   /' >&2
if [[ "$DEV_MODE" -eq 1 ]]; then
  _expected="$(printf '%s\n' "$R9_STAGED_ALLOW" | sed '/^[[:space:]]*$/d' | sort -u)"
  _actual="$(printf '%s\n' "$STAGED_LIST" | sort -u)"
  [[ "$_actual" == "$_expected" ]] ||
    { echo "[DEV_COMMIT_DISABLED] staged files do not exactly match allowlist" >&2; exit 78; }
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
HEARTBEAT_PID=""
DEV_RECEIPT=""
COMMIT_HOOKS=""
LOCK_HOLDER_PID=""
COMMON_LOCK_FILE="$(git rev-parse --path-format=absolute --git-common-dir)/r9-commit.lock"
WORKTREE_LOCK_FILE="$(git rev-parse --absolute-git-dir)/r9-worktree.lock"
WORKTREE_LOCK_HOLDER_PID=""
GLOBAL_LOCK_HOLDER_PID=""
GLOBAL_LOCK_ACQUIRED=0
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
r9_acquire_lock() {
  local lock_file="$1" fd="$2" lock_tmp ack lock_ok deadline py_bin
  LOCK_HOLDER_PID=""
  if command -v flock >/dev/null 2>&1; then
    if [ "$fd" -eq 8 ]; then exec 8>"$lock_file"; else exec 9>"$lock_file"; fi
    if ! flock -w "$LOCK_TIMEOUT" "$fd"; then
      echo "R9 lock timeout (${LOCK_TIMEOUT}s): $lock_file" >&2
      return 1
    fi
    LOCK_MODE="flock(fd${fd})"
  else
    py_bin="$(command -v python3 || true)"
    [ -n "$py_bin" ] || { echo "R9 lock requires flock or python3" >&2; return 1; }
    lock_tmp="$(mktemp -d /tmp/r9lock.XXXXXX)"
    ack="$lock_tmp/ack"
    "$py_bin" -c "$LOCK_PROG" "$lock_file" "$LOCK_TIMEOUT" > "$ack" 2>&1 &
    LOCK_HOLDER_PID=$!
    lock_ok=""
    deadline=$((SECONDS + LOCK_TIMEOUT + 5))
    while [ "$SECONDS" -lt "$deadline" ]; do
      if grep -q '^ACQUIRED$' "$ack" 2>/dev/null; then lock_ok=1; break; fi
      if grep -q '^TIMEOUT$' "$ack" 2>/dev/null; then break; fi
      kill -0 "$LOCK_HOLDER_PID" 2>/dev/null || break
      sleep 0.2
    done
    rm -rf "$lock_tmp"
    if [ -z "$lock_ok" ]; then
      echo "R9 lock timeout or holder failure: $lock_file" >&2
      kill "$LOCK_HOLDER_PID" 2>/dev/null || true
      wait "$LOCK_HOLDER_PID" 2>/dev/null || true
      LOCK_HOLDER_PID=""
      return 1
    fi
    LOCK_MODE="fcntl(pid=${LOCK_HOLDER_PID})"
  fi
  echo "R9 lock acquired ($(date +%H:%M:%S) · ${LOCK_MODE} @ ${lock_file})"
}
# Idempotent in both flock and fcntl modes; a second fcntl holder would
# deadlock against the first. Dev keeps its original full-lock contract.
r9_acquire_global_lock() {
  if [ "$GLOBAL_LOCK_ACQUIRED" -eq 1 ]; then return 0; fi
  r9_acquire_lock "$COMMON_LOCK_FILE" 9 || return 1
  GLOBAL_LOCK_HOLDER_PID="$LOCK_HOLDER_PID"
  LOCK_HOLDER_PID=""
  GLOBAL_LOCK_ACQUIRED=1
}
r9_release_global_lock() {
  if [ -n "$GLOBAL_LOCK_HOLDER_PID" ]; then
    kill "$GLOBAL_LOCK_HOLDER_PID" 2>/dev/null || true
    wait "$GLOBAL_LOCK_HOLDER_PID" 2>/dev/null || true
    GLOBAL_LOCK_HOLDER_PID=""
  fi
  flock -u 9 2>/dev/null || true
  GLOBAL_LOCK_ACQUIRED=0
}
r9_release_locks() {
  local pid
  r9_release_global_lock
  for pid in "$WORKTREE_LOCK_HOLDER_PID" "$LOCK_HOLDER_PID"; do
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  flock -u 8 2>/dev/null || true
}
trap 'r9_release_locks' EXIT
# Both paths serialize the same worktree, always before the common lock.
r9_acquire_lock "$WORKTREE_LOCK_FILE" 8
WORKTREE_LOCK_HOLDER_PID="$LOCK_HOLDER_PID"
LOCK_HOLDER_PID=""
if [ "$DEV_MODE" -eq 1 ]; then r9_acquire_global_lock; fi

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
HEAD_REF="$(git symbolic-ref -q HEAD || true)"
TREE="$(git write-tree)"
# The pre-lock whitelist can become stale while waiting. Recheck the exact
# candidate tree, not the mutable index, under the checkout lock.
if [ -n "${R9_STAGED_ALLOW:-}" ]; then
  if [ -n "$(comm -23 <(git diff --name-only "$HEAD_NOW" "$TREE" | sort -u) \
      <(printf '%s\n' "$R9_STAGED_ALLOW" | sed '/^[[:space:]]*$/d' | sort -u))" ]; then
    echo "[R9_CANDIDATE_STALE] staged paths changed outside the allowed scope" >&2
    exit 1
  fi
fi
PROBE="$(printf '%s\n' "$MSG" | git commit-tree "$TREE" -p "$HEAD_NOW")"
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
# Gate receipts use unique paths unless the caller explicitly supplies one.
REGISTRY="tests/guards/external_red_registry.json"
FIXTURE_MANIFEST="tests/guards/fixture_manifest.json"
# PROBE checkout must live under a trusted (non-world-writable) ancestor:
# rootless canary tests reject any world-writable ancestor chain, and macOS
# exposes /tmp as /private/tmp (mode 1777). Default to $HOME/.cache/lfl-r9probe:
# OUTSIDE the repo (the dev-commit flow treats any untracked in-repo file as
# tree pollution, so an in-repo probe tree breaks minimal test repos without a
# .gitignore) with a fully trusted ancestor chain ($HOME is never
# world-writable). R9_PROBE_ROOT lets foreign CI pin its own trusted root;
# with neither HOME nor R9_PROBE_ROOT we FAIL CLOSED (exit 78) instead of
# guessing a location that could pollute the repo. mktemp -d still
# creates the probe dir itself as 0700.
if [ -z "${HOME:-}" ] && [ -z "${R9_PROBE_ROOT:-}" ]; then
  echo "[R9_PROBE_REJECTED] no HOME and no R9_PROBE_ROOT: cannot pick a trusted probe root" >&2
  exit 78
fi
if [ -n "${HOME:-}" ]; then
  R9_PROBE_BASE="$HOME/.cache/lfl-r9probe"
else
  R9_PROBE_BASE="$(git rev-parse --show-toplevel)/.cache/lfl-r9probe"
fi
R9_PROBE_BASE="${R9_PROBE_ROOT:-$R9_PROBE_BASE}"
mkdir -p "$R9_PROBE_BASE"
PROBE_WT="$(mktemp -d "$R9_PROBE_BASE/r9probe.XXXXXX")"
# Git lists physical paths (e.g. /private/tmp on macOS), not symlink aliases.
PROBE_WT="$(cd "$PROBE_WT" && pwd -P)"
r9_stop_heartbeat() {
  if [ -n "${HEARTBEAT_PID:-}" ]; then
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
  fi
}
r9_archive_receipt() {
  local destination="$1" temporary
  temporary="$(mktemp "${destination}.XXXXXX")" || return 1
  if ! cp "$GATE_LOG" "$temporary" || ! mv -f "$temporary" "$destination"; then
    rm -f "$temporary" || true
    return 1
  fi
}
r9_cleanup_exit() {
  local result="$1"
  r9_stop_heartbeat
  r9_release_global_lock
  if [ -n "${COMMIT_HOOKS:-}" ]; then rm -rf "$COMMIT_HOOKS"; fi
  if [ -n "${PROBE_WT:-}" ]; then
    if ! r9_cleanup_probe "$PROBE_WT"; then
      if [ "$result" -eq 0 ]; then result=1; fi
    fi
  fi
  if [ -n "${GATE_LOG:-}" ]; then
    # One authoritative last receipt per worktree; atomic replacement avoids
    # partial readers. Keep the legacy global last-completed alias for tooling,
    # but never use it as candidate-specific evidence. Explicit paths are kept.
    local receipt="${R9_GATE_RECEIPT_FILE:-$(git rev-parse --absolute-git-dir)/r9_gate_last.log}"
    local archived=0
    if [ -n "${R9_GATE_RECEIPT_FILE:-}" ]; then
      # Preserve caller-supplied destination semantics (symlink/device/FIFO,
      # existing file permissions) from the original wrapper.
      cp "$GATE_LOG" "$receipt" && archived=1
    else
      r9_archive_receipt "$receipt" && archived=1
    fi
    if [ "$archived" -eq 0 ]; then
      echo "R9 gate receipt archive failed: $GATE_LOG" >&2
      if [ "$result" -eq 0 ]; then result=1; fi
    else
      echo "R9 gate receipt: $receipt"
      if [ -z "${R9_GATE_RECEIPT_FILE:-}" ]; then
        r9_archive_receipt /tmp/r9_gate_last.log || echo "R9 legacy receipt alias unavailable" >&2
      fi
    fi
    rm -f "$GATE_LOG" "$GATE_LOG.fails" || true
  fi
  if [ -n "${DEV_RECEIPT:-}" ]; then rm -f "$DEV_RECEIPT" || true; fi
  r9_release_locks
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

r9_assert_candidate() {
  if [ "$(git rev-parse HEAD)" != "$HEAD_NOW" ] ||
     [ "$(git symbolic-ref -q HEAD || true)" != "$HEAD_REF" ] ||
     [ "$(git write-tree)" != "$TREE" ]; then
    echo "[R9_CANDIDATE_STALE] HEAD/ref/index changed during isolated gate; refusing commit" >&2
    return 1
  fi
}
# Keep native git commit on the real branch/worktree. A command-local
# reference-transaction hook checks the exact object BEFORE Git publishes
# the ref, while forwarding every existing executable hook unchanged in
# its original cwd/argv. No persistent hooksPath change or manual ref update.
r9_publish_checked_commit() {
  local original_hooks
  r9_assert_candidate || return 1
  original_hooks="$(git rev-parse --path-format=absolute --git-path hooks)" || return 1
  COMMIT_HOOKS="$(mktemp -d "$R9_PROBE_BASE/r9hooks.XXXXXX")" || return 1
  python3 - "$original_hooks" "$COMMIT_HOOKS" "$HEAD_NOW" "$HEAD_REF" "$TREE" "$CHECK" <<'R9_HOOKS_PY' || return 1
import os, pathlib, re, shlex, subprocess, sys
original, target = map(pathlib.Path, sys.argv[1:3])
base, ref, tree, check = sys.argv[3:]
version = re.search(r"git version (\d+)\.(\d+)", subprocess.check_output(["git", "--version"], text=True))
if not version or tuple(map(int, version.groups())) < (2, 29):
    sys.exit("R9 requires Git reference-transaction support (>=2.29)")
for hook in original.iterdir() if original.is_dir() else ():
    if hook.name == "reference-transaction" or not hook.is_file() or not os.access(hook, os.X_OK):
        continue
    wrapper = target / hook.name
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(str(hook)) + ' "$@"\n')
    wrapper.chmod(0o700)
original_ref = original / "reference-transaction"
if not original_ref.is_file() or not os.access(original_ref, os.X_OK):
    original_ref = None
hook = target / "reference-transaction"
hook.write_text("#!/usr/bin/env python3\n" + f"BASE={base!r}\nREF={ref!r}\nTREE={tree!r}\nCHECK={check!r}\nORIGINAL={str(original_ref) if original_ref else ''!r}\n" + '''import subprocess, sys
payload = sys.stdin.buffer.read()
phase = sys.argv[1]
if ORIGINAL:
    result = subprocess.run([ORIGINAL, phase], input=payload)
    if result.returncode:
        sys.exit(result.returncode)
if phase == "prepared":
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    for line in payload.decode("utf-8", "surrogateescape").splitlines():
        old, new, name = line.split(" ", 2)
        if name != "HEAD" and not name.startswith("refs/heads/"):
            continue
        current = subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], text=True, capture_output=True).stdout.strip()
        if (name not in (REF or "HEAD", "HEAD") or current != REF or old != BASE
                or git("rev-parse", new + "^{tree}") != TREE
                or git("rev-list", "--parents", "-n", "1", new).split() != [new, BASE]):
            sys.exit("[R9_CANDIDATE_STALE] hook changed candidate tree/parent/ref; original ref untouched")
        subprocess.run(["bash", CHECK, new], check=True)
''')
hook.chmod(0o700)
R9_HOOKS_PY
  r9_assert_candidate || return 1
  git -c core.hooksPath="$COMMIT_HOOKS" commit -m "$MSG" || return 1
  if [ "$(git rev-parse HEAD^{tree})" != "$TREE" ] ||
     [ "$(git rev-parse HEAD^)" != "$HEAD_NOW" ]; then
    echo "[R9_CANDIDATE_STALE] unexpected native commit identity" >&2
    return 1
  fi
}

# Dev-only local commit: same global lock, exact staged PROBE, fixture
# verification, machine checks, staged scan and Git hooks. No R9 receipt,
# no release qualification and no Host review/PR bypass. Any missing trusted
# Host installation/activation/one-use grant is a hard refusal.
if [[ "$DEV_MODE" -eq 1 ]]; then
  [[ "$HEAD_NOW" == "$BASE_HEAD" ]] ||
    { echo "[DEV_COMMIT_DISABLED] queue advanced while waiting" >&2; exit 78; }
  [[ -z "$(git diff --name-only)" &&
     -z "$(git ls-files --others --exclude-standard)" &&
     "$(git write-tree)" == "$TREE" ]] ||
    { echo "[DEV_COMMIT_DISABLED] staged tree not clean or changed" >&2; exit 78; }
  bash scripts/git_security_scan.sh --staged
  DEV_RECEIPT="$(mktemp /tmp/lfl-dev-commit.XXXXXXXX)"
  COMMON_DIR="$(git rev-parse --path-format=absolute --git-common-dir)"
  AUDIT_DIR="$(dirname "$COMMON_DIR")/data/audit"
  env -u LFL_PYTHON -u PYTHONPATH -u PYTHONHOME -u PYTEST_ADDOPTS \
    -u PYTEST_PLUGINS -u PYTEST_DISABLE_PLUGIN_AUTOLOAD \
    -u PYTHONSTARTUP -u PYTHONINSPECT bash scripts/dev_gate.sh \
    --goal "$DEV_GOAL" --req "$DEV_REQ" --base "$DEV_BASE" \
    --design "$DEV_DESIGN" --audit-dir "$AUDIT_DIR" \
    --receipt "$DEV_RECEIPT"
  [[ "$(git write-tree)" == "$TREE" && "$(git rev-parse HEAD)" == "$HEAD_NOW" ]] ||
    { echo "[DEV_COMMIT_DISABLED] candidate changed during incremental gate" >&2; exit 78; }
  MSG_SHA="$(printf '%s' "$MSG" | /usr/bin/python3 -I -S -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
  HOST_REPLY="$(/usr/bin/sudo -n -u _lfl_dual_witness /usr/bin/python3 -I -S \
    "$HOST_DEV_AUTH" consume \
    --worktree "$PWD" --goal "$DEV_GOAL" --req "$DEV_REQ" \
    --base "$DEV_BASE" --message-sha256 "$MSG_SHA" \
    --grant-id "$DEV_GRANT" < "$DEV_RECEIPT")" ||
    { echo "[DEV_COMMIT_DISABLED] Host refused one-use grant" >&2; exit 78; }
  printf '%s' "$HOST_REPLY" | /usr/bin/python3 -I -S -c '
import json,sys
try:
    d=json.load(sys.stdin)
    ok=(d.get("decision")=="CONSUMED" and d.get("grant_id")==sys.argv[1]
        and d.get("tree")==sys.argv[2] and d.get("release_qualified") is False)
except (ValueError,TypeError,AttributeError):
    ok=False
sys.exit(0 if ok else 1)
' "$DEV_GRANT" "$TREE" ||
    { echo "[DEV_COMMIT_DISABLED] Host consumption response invalid" >&2; exit 78; }
  [[ "$(git write-tree)" == "$TREE" && "$(git rev-parse HEAD)" == "$HEAD_NOW" &&
     -z "$(git diff --name-only)" ]] ||
    { echo "[DEV_COMMIT_DISABLED] candidate changed after Host consumption" >&2; exit 78; }
  r9_publish_checked_commit || exit 78
  echo "[DEV_COMMIT_ONLY] Local commit created; no R9, Host review, push or release qualification."
  exit 0
fi

GATE_LOG="$(mktemp /tmp/r9_gate.XXXXXX)"
GATE_EXIT=0
# Low-frequency heartbeat on the job stream, separate from the parsed gate
# receipt. Only sample descendants of this wrapper; no extra Web polling.
python3 -u - "$$" "$GATE_LOG" <<'R9_HEARTBEAT' &
import datetime, os, subprocess, sys, time
root, log = int(sys.argv[1]), sys.argv[2]
started = time.monotonic()
while os.getppid() == root:
    time.sleep(30)
    if os.getppid() != root:
        break
    try:
        rows = subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,pcpu=,rss="], text=True, timeout=3
        ).splitlines()
        procs = {}
        for row in rows:
            pid, parent, cpu, rss = row.split()
            procs[int(pid)] = (int(parent), float(cpu), int(rss))
        owned = {root}
        while True:
            more = {pid for pid, (parent, _, _) in procs.items() if parent in owned}
            if more <= owned:
                break
            owned.update(more)
        cpu = sum(procs[p][1] for p in owned if p in procs)
        rss = sum(procs[p][2] for p in owned if p in procs) / 1024
        st = os.stat(log)
        activity = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S")
        print(f"\n[R9_PROGRESS] elapsed={int(time.monotonic()-started)}s "
              f"cpu_sum={cpu:.1f}% rss_sum={rss:.0f}MiB last_log={activity} "
              f"log_bytes={st.st_size}", flush=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        print(f"\n[R9_PROGRESS] elapsed={int(time.monotonic()-started)}s metrics=unavailable", flush=True)
R9_HEARTBEAT
HEARTBEAT_PID=$!
# Stream the same bytes to the JobRegistry and the durable receipt. Preserve
# both exit statuses: a failed log writer is an infrastructure failure.
set +e
(cd "$PROBE_WT" && bash scripts/ci_gate.sh) 2>&1 | tee "$GATE_LOG"
GATE_STATUS=("${PIPESTATUS[@]}")
set -e
r9_stop_heartbeat
GATE_EXIT="${GATE_STATUS[0]}"
if [ "${GATE_STATUS[1]}" -ne 0 ] || [ "$GATE_EXIT" -eq 125 ]; then
  echo "R9 gate logging infrastructure failed" >&2
  exit 125
fi
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
r9_acquire_global_lock
r9_assert_candidate
bash scripts/git_security_scan.sh --staged
r9_publish_checked_commit
echo "✅ R9 提交完成（机检 + 门禁 + 提交三步全绿）"
