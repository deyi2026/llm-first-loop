#!/usr/bin/env bash
# 飞书桥优雅重启脚本（M46，2026-08-11；P1-2-R5 健康检查口径统一为心跳新鲜度）
#
# 用法:
#   scripts/restart_feishu.sh            # 重启（无进程则启动）
#   scripts/restart_feishu.sh start      # 启动
#   scripts/restart_feishu.sh stop       # 优雅停止（SIGTERM → 超时强杀）
#   scripts/restart_feishu.sh status     # 状态查询
#
# 设计要点:
#   1. 凭证不硬编码: 环境变量优先（FEISHU_APP_ID/FEISHU_APP_SECRET），
#      缺失时读取项目 .feishu.env（llm-first-loop 独立飞书 app；勿用 本地既有实现 凭证）。
#   2. 优雅停机: SIGTERM → 等待 GRACE_S 内自然退出 → 超时 SIGKILL。
#   3. 健康检查: 心跳文件新鲜度（mtime ≤ 90s，与 restart_system.sh 口径一致）。
#      P1-2-R5: 移除 lsof/WS_HOST TCP 判定——断线重连（SDK 常态）不误报不健康。
#   4. 幂等安全: 已运行则先停再启；PID 文件 + pgrep 双校验防误杀。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

VENV_PY="$PROJECT_DIR/.venv/bin/python"
LOG_FILE="$PROJECT_DIR/data/feishu_bridge.log"
PID_FILE="$PROJECT_DIR/data/feishu_bridge.pid"
BRIDGE_MOD="llm_loop.feishu"
HEARTBEAT_FILE="$PROJECT_DIR/data/feishu_heartbeat.json"

# 可调参数（env 覆盖）
GRACE_S="${FEISHU_GRACE_S:-15}"            # 优雅停机等待秒数
STARTUP_WAIT_S="${FEISHU_STARTUP_WAIT_S:-20}"  # 启动健康检查等待秒数
STARTUP_POLL_S="${FEISHU_STARTUP_POLL_S:-2}"   # 健康检查轮询间隔
HEARTBEAT_FRESH_S="${FEISHU_HEARTBEAT_FRESH_S:-90}"  # 心跳新鲜阈值（与 restart_system.sh 一致）

_log() { printf '[restart_feishu] %s\n' "$*"; }
_die() { printf '[restart_feishu] ERROR: %s\n' "$*" >&2; exit 1; }

# ── 进程定位（PID 文件 + pgrep 双校验）──
_current_pid() {
  local pid=""
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%s' "$pid"
      return 0
    fi
  fi
  # PID 文件失效 → pgrep 兜底（防残留误判）
  pid="$(pgrep -f "$BRIDGE_MOD" | head -1 || true)"
  printf '%s' "$pid"
}

_is_running() { [[ -n "$(_current_pid)" ]]; }

# ── P1-2-R5: 心跳新鲜度判定（与 restart_system.sh feishu 口径一致）──
# 0=健康; 非0=不健康/需升级（进程死 / 心跳文件缺失 / 心跳过期 / stat 不可用回退 0 → 判不健康如实）
_heartbeat_healthy() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 1
  [[ -f "$HEARTBEAT_FILE" ]] || return 1
  local hb_mtime now_s
  hb_mtime="$(stat -f %m "$HEARTBEAT_FILE" 2>/dev/null || stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || echo 0)"
  [[ "$hb_mtime" =~ ^[0-9]+$ ]] || return 1
  now_s="$(date +%s)"
  (( now_s - hb_mtime <= HEARTBEAT_FRESH_S ))
}

# ── 凭证注入（环境优先 → 项目 .feishu.env 回退；llm-first-loop 独立飞书 app，勿用 本地既有实现）──
_load_credentials() {
  if [[ -n "${FEISHU_APP_ID:-}" && -n "${FEISHU_APP_SECRET:-}" ]]; then
    _log "凭证: 来自环境变量"
    return 0
  fi
  local feishu_env="$PROJECT_DIR/.feishu.env"
  if [[ -f "$feishu_env" ]]; then
    local app_id app_secret
    app_id="$(grep -m1 '^FEISHU_APP_ID=' "$feishu_env" | cut -d= -f2- || true)"
    app_secret="$(grep -m1 '^FEISHU_APP_SECRET=' "$feishu_env" | cut -d= -f2- || true)"
    if [[ -n "$app_id" && -n "$app_secret" ]]; then
      export FEISHU_APP_ID="$app_id"
      export FEISHU_APP_SECRET="$app_secret"
      _log "凭证: 读取 ${feishu_env}（llm-first-loop 独立飞书 app）"
      return 0
    fi
  fi
  _die "FEISHU_APP_ID/FEISHU_APP_SECRET 未配置（export 或 ${feishu_env} 提供；勿用 本地既有实现 凭证）"
}


# ── LLM 注入（LLM_API_KEY 环境优先 → DEEPSEEK_API_KEY 回退）──
_load_llm() {
  export LLM_API_KEY="${LLM_API_KEY:-${DEEPSEEK_API_KEY:-}}"
  export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com/v1}"
  export LLM_MODEL="${LLM_MODEL:-deepseek-v4-flash}"
  export SUMMARY_MODE="${SUMMARY_MODE:-sync}"      # EVO-20260811: 压缩主动化 LLM 摘要
  export TOOL_SCHEMA_LAZY="${TOOL_SCHEMA_LAZY:-1}" # EVO-20260811: 工具 Schema 懒加载
  if [[ -z "$LLM_API_KEY" ]]; then
    _die "LLM_API_KEY / DEEPSEEK_API_KEY 未配置"
  fi
}

# ── 优雅停止 ──
_stop() {
  local pid="$(_current_pid)"
  if [[ -z "$pid" ]]; then
    _log "未运行，跳过停止"
    rm -f "$PID_FILE"
    return 0
  fi
  _log "停止进程 ${pid}（SIGTERM，等待 ${GRACE_S}s）..."
  kill "$pid" 2>/dev/null || true
  local waited=0
  while kill -0 "$pid" 2>/dev/null && (( waited < GRACE_S )); do
    sleep 1
    (( waited += 1 ))
  done
  if kill -0 "$pid" 2>/dev/null; then
    _log "超时未退出，SIGKILL 强杀 $pid"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  else
    _log "已优雅退出（${waited}s）"
  fi
  rm -f "$PID_FILE"
}

# ── 启动 + 健康检查（P1-2-R5: 心跳口径；进程存活但心跳未新鲜 → 如实警告不静默成功）──
_start() {
  if _is_running; then
    _log "已在运行（PID $(_current_pid)），无需启动"
    return 0
  fi
  _load_credentials
  _load_llm
  mkdir -p "$PROJECT_DIR/data"
  # P1-3-R2: 注入优雅退出时间契约（wait+drain ≤ GRACE_S−余量；10+3=13 ≤ 15，env 可覆盖）
  export FEISHU_EXIT_WAIT_S="${FEISHU_EXIT_WAIT_S:-10}"
  export FEISHU_EXIT_DRAIN_S="${FEISHU_EXIT_DRAIN_S:-3}"
  _log "启动飞书桥（日志: ${LOG_FILE}）..."
  nohup "$VENV_PY" -m "$BRIDGE_MOD" >> "$LOG_FILE" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$PID_FILE"
  _log "新进程 PID ${new_pid}，健康检查（${STARTUP_WAIT_S}s 超时）..."
  local waited=0
  while (( waited < STARTUP_WAIT_S )); do
    if ! kill -0 "$new_pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      _die "进程启动即退出（详见 $LOG_FILE 尾部）"
    fi
    if _heartbeat_healthy "$new_pid"; then
      _log "心跳新鲜（mtime ≤ ${HEARTBEAT_FRESH_S}s）✓"
      return 0
    fi
    sleep "$STARTUP_POLL_S"
    (( waited += STARTUP_POLL_S ))
  done
  # 超时：进程存活但心跳未新鲜 → 保留进程并如实提示（不静默宣称成功）
  _log "警告: ${STARTUP_WAIT_S}s 内未确认心跳（进程仍在，检查 ${LOG_FILE}；旧进程未接入心跳需升级）"
  return 0
}

_status() {
  if _is_running; then
    local pid="$(_current_pid)"
    _log "运行中: PID $pid"
    if [[ -f "$HEARTBEAT_FILE" ]]; then
      if _heartbeat_healthy "$pid"; then
        _log "心跳: 新鲜（健康）"
        # 读取心跳 JSON 展示诊断明细（state/reconnect/disconnect）
        if command -v python3 >/dev/null 2>&1; then
          python3 - "$HEARTBEAT_FILE" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    hb = json.load(open(sys.argv[1], encoding="utf-8"))
    print(f"[restart_feishu]   state={hb.get('state')} reconnect_count={hb.get('reconnect_count')} disconnect_count={hb.get('disconnect_count')} ping_timeout_count={hb.get('ping_timeout_count')}")
except Exception:
    pass
PYEOF
        fi
      else
        _log "心跳: 过期（可能假死/异常，mtime > ${HEARTBEAT_FRESH_S}s）"
      fi
    else
      _log "心跳文件缺失（旧进程未接入心跳，需升级重启接入防护）"
    fi
  else
    _log "未运行"
  fi
}

# ── 主入口 ──
case "${1:-restart}" in
  start)    _start ;;
  stop)     _stop ;;
  restart)  _stop; _start ;;
  status)   _status ;;
  *)        _die "未知命令: $1（支持 start/stop/restart/status）" ;;
esac