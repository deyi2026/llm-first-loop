#!/usr/bin/env bash
# dsh_feishu.sh — DSH 飞书桥服务管理（@dsh-feishu/dsh-feishu 插件，独立 feishu profile）
#
# 用法: scripts/dsh_feishu.sh {start|stop|restart|status}
# 日志: data/dsh_feishu.log      PID: data/dsh_feishu.pid
# 运行簿: docs/local/DSH-FEISHU-RUNBOOK-20260821.md
#
# 说明:
# - 以默认 DSH_HOME（~/.dsh）启动 `dsh --profile feishu`，与 :3080 web 实例共享
#   会话/工作区（插件设计能力：飞书上的 /sessions 可接续 web 端会话）。
# - 飞书应用凭据两种来源（任选其一，见运行簿）:
#   ① profile 补丁（~/.dsh/profiles/feishu/cordis.patch.yml 的 appId/appSecret，
#      dsh-feishu-setup 向导写入）;
#   ② 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET（本脚本优先读取
#      $PROJECT_DIR/.feishu.env.dsh，其次环境变量）。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
LOG="$DATA_DIR/dsh_feishu.log"
PID_FILE="$DATA_DIR/dsh_feishu.pid"
EXIT_LOG="$DATA_DIR/dsh_feishu_exit.log"
DSH_BIN="${DSH_BIN:-$(command -v dsh || echo "$HOME/.hermes/node/bin/dsh")}"

_log() { echo "[dsh-feishu] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# 凭据注入：.feishu.env.dsh（项目内，不入库）→ 环境变量
_feishu_env() {
  local env_file="$PROJECT_DIR/.feishu.env.dsh"
  if [[ -f "$env_file" ]]; then
    export FEISHU_APP_ID="${FEISHU_APP_ID:-$(grep -m1 '^FEISHU_APP_ID=' "$env_file" | cut -d= -f2- || true)}"
    export FEISHU_APP_SECRET="${FEISHU_APP_SECRET:-$(grep -m1 '^FEISHU_APP_SECRET=' "$env_file" | cut -d= -f2- || true)}"
  fi
  # 兜底：.feishu.env（与 LFL 桥同名文件，但 DSH 用独立应用，勿混淆——见运行簿 §2.3）
  if [[ -f "$PROJECT_DIR/.feishu.env" && -z "${FEISHU_APP_ID:-}" ]]; then
    _log "⚠ 未找到 .feishu.env.dsh；回退读取 .feishu.env（若与 LFL 共用同一应用会冲突，请确认）"
    export FEISHU_APP_ID="$(grep -m1 '^FEISHU_APP_ID=' "$PROJECT_DIR/.feishu.env" | cut -d= -f2- || true)"
    export FEISHU_APP_SECRET="$(grep -m1 '^FEISHU_APP_SECRET=' "$PROJECT_DIR/.feishu.env" | cut -d= -f2- || true)"
  fi
}

_pid_alive() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid; pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start() {
  if _pid_alive; then
    _log "已在运行（pid $(cat "$PID_FILE")）"
    return 0
  fi
  _feishu_env
  if [[ -z "${FEISHU_APP_ID:-}" && -z "${FEISHU_APP_SECRET:-}" ]]; then
    # 未注入环境变量 → 依赖 profile 补丁中的 appId/appSecret（向导写入）；二者皆无则报错
    if ! grep -q "appId\|app_id" "$HOME/.dsh/profiles/feishu/cordis.patch.yml" 2>/dev/null; then
      _log "✗ 未找到飞书应用凭据：请先配置（见 docs/local/DSH-FEISHU-RUNBOOK-20260821.md §3）"
      return 2
    fi
  fi
  mkdir -p "$DATA_DIR"
  _rotate_log
  _log "启动 dsh --profile feishu（日志: ${LOG}）..."
  nohup "$DSH_BIN" --profile feishu >>"$LOG" 2>&1 &
  echo "$!" > "$PID_FILE"
  sleep 2
  if _pid_alive; then
    _log "已启动（pid $(cat "$PID_FILE")）；等待 [feishu] bridge ready..."
  else
    _log "✗ 启动失败（进程已退出），最近日志:"
    tail -20 "$LOG" || true
    return 1
  fi
}

stop() {
  if ! _pid_alive; then
    _log "未在运行"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid; pid="$(cat "$PID_FILE")"
  _log "停止（pid ${pid}）..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 15); do
    _pid_alive || break
    sleep 1
  done
  if _pid_alive; then
    _log "15s 未退出，强制 kill"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  _log "已停止"
}

status() {
  if _pid_alive; then
    _log "运行中（pid $(cat "$PID_FILE")）"
    local log_file="$LOG"
    if [[ -f "$log_file" ]]; then
      echo "  最近日志:"
      tail -5 "$log_file" | sed 's/^/    /'
    fi
    return 0
  fi
  _log "未运行"
  return 3
}

_rotate_log() {
  if [[ -f "$LOG" ]]; then
    local size; size=$(stat -f%z "$LOG" 2>/dev/null || echo 0)
    if (( size > 20 * 1024 * 1024 )); then
      mv "$LOG" "$LOG.1" 2>/dev/null || true
    fi
  fi
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "用法: $0 {start|stop|restart|status}"; exit 1 ;;
esac
