#!/usr/bin/env bash
# launch_browser_profile.sh — R1 专用 profile 启动器（DESIGN-20261005-browser-channel-hardening §4.1 v4）
#
# 用法: scripts/launch_browser_profile.sh <name> [--cdp-port N] [--ephemeral] [--headless]
#   name        data/runtime/browser-profiles/<name>/（首启自动 700 + 全树 go-rwx 收紧）
#   --cdp-port  显式端口（覆写 <profile>/port，此后复用）
#   --ephemeral 一次性隔离 profile：加 --use-mock-keychain --password-store=basic（不唤醒 macOS Keychain；
#               与 qualification 脚本 smc_browser_live_navigation.py:175-186 同契约）
#               persistent dedicated profile 默认【不携带】这两个 flag——那会把长生命周期 profile 的
#               凭据静态保护降级为明文级存储（v4-G1）。若 persistent 首启实际触发 Keychain prompt，
#               单独做 credential-at-rest qualification，不静默继承测试 flag。
#   --headless  仅用于登录完毕后的纯执行任务；首次登录必须 headed（人工完成）
#
# 端口策略（v4-G9）：首次随机 30000-39999 空闲端口持久化 <profile>/port，此后复用；
# 端口被未知 PID 占用 → fail-closed 拒启；被本脚本已记录且存活的 PID 占用 → 幂等报告。
set -euo pipefail

die() { echo "launch_browser_profile: ERROR: $*" >&2; exit 1; }

NAME="" OPT_PORT="" EPHEMERAL=0 HEADLESS=0
while (( $# )); do
  case "$1" in
    --cdp-port) OPT_PORT="${2:?--cdp-port needs a value}"; shift 2 ;;
    --ephemeral) EPHEMERAL=1; shift ;;
    --headless) HEADLESS=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [[ -z "$NAME" ]] || die "unexpected extra arg: $1"; NAME="$1"; shift ;;
  esac
done
[[ -n "$NAME" ]] || die "usage: $0 <name> [--cdp-port N] [--ephemeral] [--headless]"
[[ "$NAME" != */* && "$NAME" != .* ]] || die "profile name must be a plain name, got: $NAME"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILES_ROOT="$REPO_ROOT/data/runtime/browser-profiles"
PROFILE_DIR="$PROFILES_ROOT/$NAME"
PORT_FILE="$PROFILE_DIR/port"
PID_FILE="$PROFILE_DIR/chrome.pid"
LOG_FILE="$PROFILE_DIR/chrome.log"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[[ -x "$CHROME_BIN" ]] || die "chrome binary not found: $CHROME_BIN (override with CHROME_BIN=)"

umask 077
mkdir -p "$PROFILE_DIR"
chmod 700 "$PROFILE_DIR"

# 首启（无 port 文件）：全树收紧权限（此后 Chrome 自建文件受 umask 077 约束）
if [[ ! -f "$PORT_FILE" ]]; then
  chmod -R go-rwx "$PROFILE_DIR" 2>/dev/null || true
fi

# ---- 端口选择：显式 > 持久化 > 随机首启 ----
if [[ -n "$OPT_PORT" ]]; then
  PORT="$OPT_PORT"
elif [[ -f "$PORT_FILE" ]]; then
  PORT="$(<"$PORT_FILE")"
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "corrupt port file $PORT_FILE: '$PORT'"
else
  PORT=""
  for _ in $(seq 1 50); do
    CAND=$(( (RANDOM % 10000) + 30000 ))
    if ! lsof -nP -iTCP:"$CAND" -sTCP:LISTEN >/dev/null 2>&1; then PORT="$CAND"; break; fi
  done
  [[ -n "$PORT" ]] || die "no free port found in 30000-39999 after 50 tries"
fi
printf '%s\n' "$PORT" > "$PORT_FILE"
chmod 600 "$PORT_FILE"

# ---- 占用检查（v4-G9 fail-closed）----
LISTEN_PIDS=()
while IFS= read -r p; do LISTEN_PIDS+=("$p"); done < <(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN || true)
if (( ${#LISTEN_PIDS[@]} > 0 )); then
  OWN_PID=""
  if [[ -f "$PID_FILE" ]]; then
    CAND_PID="$(<"$PID_FILE")"
    for p in "${LISTEN_PIDS[@]}"; do
      if [[ "$p" == "$CAND_PID" ]] && kill -0 "$CAND_PID" 2>/dev/null; then OWN_PID="$p"; fi
    done
  fi
  if [[ -n "$OWN_PID" ]]; then
    echo "already running: chrome pid=$OWN_PID port=$PORT profile=$PROFILE_DIR"
    echo "(to restart: kill $OWN_PID first)"
    exit 0
  fi
  die "port $PORT occupied by unknown PID(s): ${LISTEN_PIDS[*]} — refusing to launch (fail-closed)"
fi

# ---- argv 组装（§4.1 凭据两档）----
ARGV=( "$CHROME_BIN"
  "--user-data-dir=$PROFILE_DIR"
  "--remote-debugging-address=127.0.0.1"
  "--remote-debugging-port=$PORT"
  "--no-first-run"
  "--no-default-browser-check" )
if (( EPHEMERAL )); then
  ARGV+=( "--use-mock-keychain" "--password-store=basic" )
fi
if (( HEADLESS )); then
  ARGV+=( "--headless=new" )
fi
# 唯一 page（about:blank）：保证 TARGET_ID 留空时自动绑定唯一 page 的契约成立
ARGV+=( "about:blank" )

# ---- 启动 ----
MODE="persistent"; (( EPHEMERAL )) && MODE="ephemeral"
UI="headed"; (( HEADLESS )) && UI="headless"
nohup "${ARGV[@]}" >>"$LOG_FILE" 2>&1 &
CHROME_PID=$!
printf '%s\n' "$CHROME_PID" > "$PID_FILE"
chmod 600 "$PID_FILE"

# 失败路径防孤儿：EXIT trap 兜底（die 在 ||/&& 条件上下文里不触发 ERR trap，
# 实测 2026-10-06：IPv4 端口被占时 Chrome 回退绑 [::1]，旧 ERR 方案泄漏了存活 Chrome）
CHROME_LAUNCHED=1
cleanup_on_fail() {
  if [[ -n "${CHROME_LAUNCHED:-}" ]]; then
    kill "$CHROME_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
}
trap cleanup_on_fail EXIT

# ---- 监听者断言 + 等待调试端点 ----
# 断言：本 PID 必须以 IPv4 127.0.0.1:<port> 形态 LISTEN（防端口被抢后 Chrome 回退绑 [::1]：
# 那时它自己的 PID 也会出现在 LISTEN 名单，纯 PID 匹配放行，最终只能靠端点超时兜底）
LISTEN_OK=0
for _ in $(seq 1 24); do
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk -v pid="$CHROME_PID" -v port="$PORT" \
      '$2==pid && index($9, "127.0.0.1:" port)==1 { found=1 } END { exit(found?0:1) }'; then
    LISTEN_OK=1; break
  fi
  kill -0 "$CHROME_PID" 2>/dev/null || break
  sleep 0.25
done
if (( ! LISTEN_OK )); then
  tail -n 10 "$LOG_FILE" >&2 || true
  die "chrome pid=$CHROME_PID never LISTENed on :$PORT (port snatched / IPv6 fallback / exited) — killing"
fi

UP=0
for _ in $(seq 1 60); do
  if curl -s --noproxy '*' --max-time 2 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; then UP=1; break; fi
  kill -0 "$CHROME_PID" 2>/dev/null || { tail -n 20 "$LOG_FILE" >&2; die "chrome exited during startup (pid=$CHROME_PID)"; }
  sleep 0.25
done
(( UP )) || { tail -n 20 "$LOG_FILE" >&2; die "debug endpoint did not come up on :$PORT in 15s"; }
CHROME_LAUNCHED=""   # 成功：解除 EXIT 清理

TARGET_ID_HINT="$(curl -s --noproxy '*' --max-time 2 "http://127.0.0.1:$PORT/json/list" \
  | /usr/bin/python3 -c 'import json,sys;ts=json.load(sys.stdin);ps=[t for t in ts if t.get("type")=="page"];print(ps[0]["id"] if len(ps)==1 else f"AUTO-BIND-AMBIGUOUS({len(ps)} pages)")' 2>/dev/null || true)"

echo "chrome up: pid=$CHROME_PID port=$PORT mode=$MODE ui=$UI profile=$PROFILE_DIR"
echo "page target: ${TARGET_ID_HINT:-unknown} (auto-bind contract: exactly 1 page)"
echo
echo "# --- 可粘贴进 .env（随后 restart web 生效）---"
echo "LFL_BROWSER_PERCEPTION_CDP_URL=http://127.0.0.1:$PORT"
echo "LFL_BROWSER_ACTION_ENABLED=1"
echo "#LFL_BROWSER_PERCEPTION_TARGET_ID="
echo "# ↑ 留空 = 唯一 page 自动绑定（挂载实例只开一个 page；Chrome 重拉后无需改配置+重启服务）"
