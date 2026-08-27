#!/usr/bin/env bash
# dsh_web_restart.sh — 重启 DSH web 服务（:3080，web profile）
#
# 背景（2026-08-21）：DSH 飞书桥已并入 web profile（同进程 = 飞书与 web 同一 agent/会话）。
# 插件在进程启动时加载 → 必须重启 web 进程才生效。本脚本负责优雅重启：
#   1) 找到 :3080 监听进程并 SIGTERM 等待退出（15s 上限，超时 SIGKILL）
#   2) nohup 重启 `dsh web`（日志 data/dsh_web.log，PID data/dsh_web.pid）
#   3) 轮询 / 直到就绪（最多 60s）
#
# 用法: bash scripts/dsh_web_restart.sh
# 注意: 重启会短暂中断当前 web 页面（会话数据落盘保留，刷新即恢复）。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
LOG="$DATA_DIR/dsh_web.log"
PID_FILE="$DATA_DIR/dsh_web.pid"
PORT="${DSH_WEB_PORT:-3080}"
DSH_BIN="${DSH_BIN:-$(command -v dsh || echo "$HOME/.hermes/node/bin/dsh")}"

_log() { echo "[dsh-web] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

_old_pid() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}'
}

stop_old() {
  local pid
  pid="$(_old_pid || true)"
  if [[ -z "$pid" ]]; then
    _log "端口 $PORT 无监听进程（可能已停止）"
    return 0
  fi
  _log "停止旧进程（pid ${pid}, 端口 ${PORT}）..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 15); do
    [[ -z "$(_old_pid || true)" ]] && break
    sleep 1
  done
  if [[ -n "$(_old_pid || true)" ]]; then
    _log "15s 未退出，强制 kill"
    kill -9 "$pid" 2>/dev/null || true
  fi
  _log "旧进程已停止"
}

start_new() {
  mkdir -p "$DATA_DIR"
  if [[ -f "$LOG" ]] && (( $(stat -f%z "$LOG" 2>/dev/null || echo 0) > 20 * 1024 * 1024 )); then
    mv "$LOG" "$LOG.1" 2>/dev/null || true
  fi
  _log "启动 dsh web（端口 ${PORT}, 日志: ${LOG}）..."
  nohup "$DSH_BIN" web >>"$LOG" 2>&1 &
  echo "$!" > "$PID_FILE"
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
      _log "就绪: http://127.0.0.1:$PORT/（pid $(cat "$PID_FILE")）"
      return 0
    fi
    sleep 1
  done
  _log "✗ 60s 内未就绪，最近日志:"
  tail -30 "$LOG" || true
  return 1
}

stop_old
start_new
