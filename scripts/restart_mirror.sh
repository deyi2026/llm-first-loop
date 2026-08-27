#!/usr/bin/env bash
# restart_mirror.sh — 镜像工作区常驻服务重启脚本（2026-08-22 实践整理）
#
# 管理镜像的常驻服务:
#   web    FastAPI 服务（python -m llm_loop.web，端口 8903，健康端点 GET /health）
#   feishu 飞书桥（python -m llm_loop.feishu，WS 长连接 msg-frontier.feishu.cn）
#
# ⚠️⚠️ 最重要注意事项 ⚠️⚠️
#   1. 切勿用 `pkill -f "llm_loop.web"` —— 会把主区 web（:8902）一起杀掉！
#      （主区/镜像进程命令行相同，pkill 全匹配无法区分。实证 2026-08-22 误杀主区）
#      正确做法: 按端口杀（lsof -tiTCP:$PORT），本脚本已内置。
#   2. 必须先 `source .env` 再启动 —— 进程 env 才能读到配置
#      （不 source 则 TOOL_ROUND_ZERO_HISTORY 等配置缺失/旧值。实证 2026-08-22）
#   3. PYTHONPATH 必须指向镜像 src —— 否则 editable install 会加载主区代码
#      （镜像跑主区代码 = 验证失真。实证 2026-08-22 镜像慢/行为不一致）
#   4. WEB_PORT=8903 必须显式设置 —— 否则默认 8902 与主区冲突
#   5. 飞书桥凭证必须真实 —— 镜像 .env 的 FEISHU_APP_ID/FEISHU_APP_SECRET
#      不能是占位符（cli_xxx），否则预检失败启动不了。真凭证在 .feishu.env。
#
# 用法:
#   bash scripts/restart_mirror.sh web           # 重启 web（默认）
#   bash scripts/restart_mirror.sh feishu        # 重启飞书桥
#   bash scripts/restart_mirror.sh all           # 全部重启
#   bash scripts/restart_mirror.sh status        # 查看状态

set -euo pipefail

MIRROR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$MIRROR_DIR"

VENV_PY="$MIRROR_DIR/.venv/bin/python"
WEB_PORT="8903"
WEB_HOST="127.0.0.1"

_log() { echo "[mirror] $(date '+%H:%M:%S') $*"; }

# DSH 环境隔离（2026-08-23 拷问修复 P1）:
#   1. DSH_HOME 重定向到镜像区项目内 data/dsh-home —— 否则落到全局 ~/.dsh，
#      dsh_task/dsh_session_read 的 session 目录按镜像区 workspace_key 找不到 → 失败。
#   2. 清理主区 DSH 环境残留（DSH_SESSION_JSONL/DSH_SESSION_ID/DSH_SHELL/DSH_WEB_URL）
#      —— 镜像进程若从主区 DSH 会话环境启动会携带这些变量，路径解析错指主区。
_prep_dsh_env() {
  export DSH_HOME="$MIRROR_DIR/data/dsh-home"
  mkdir -p "$DSH_HOME"
  unset DSH_SESSION_JSONL DSH_SESSION_ID DSH_SHELL DSH_WEB_URL 2>/dev/null || true
}

# 按端口找监听进程（只杀目标端口，不碰主区）
_port_pid() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}'
}

_stop_port() {
  local port="$1" pid
  pid="$(_port_pid "$port" || true)"
  if [[ -z "$pid" ]]; then
    _log "port $port 无监听进程"
    return 0
  fi
  _log "停止 pid ${pid} (port $port)..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    [[ -z "$(_port_pid "$port" || true)" ]] && break
    sleep 1
  done
  if [[ -n "$(_port_pid "$port" || true)" ]]; then
    _log "10s 未退出，强制 kill"
    kill -9 "$pid" 2>/dev/null || true
  fi
  _log "已停止"
}

_start_web() {
  _log "启动 web(port $WEB_PORT)..."
  _prep_dsh_env
  set -a && source .env && set +a
  PYTHONPATH="$MIRROR_DIR/src" WEB_PORT="$WEB_PORT" \
    nohup "$VENV_PY" -m llm_loop.web >> data/web.log 2>&1 &
  local pid=$!
  for _ in $(seq 1 30); do
    if curl -sf --max-time 2 "http://$WEB_HOST:$WEB_PORT/health" >/dev/null 2>&1; then
      _log "✅ web 就绪: http://$WEB_HOST:$WEB_PORT/(pid $pid)"
      return 0
    fi
    sleep 1
  done
  _log "✗ web 30s 未就绪，最近日志:"
  tail -10 data/web.log || true
  return 1
}

_start_feishu() {
  _log "启动飞书桥..."
  _prep_dsh_env
  set -a && source .env && set +a
  PYTHONPATH="$MIRROR_DIR/src" \
    nohup "$VENV_PY" -m llm_loop.feishu >> data/feishu.log 2>&1 &
  local pid=$!
  sleep 15
  # 校验: 预检失败会立即退出；WS 连接成功会建立到 msg-frontier.feishu.cn 的连接
  if ! kill -0 "$pid" 2>/dev/null; then
    _log "✗ 飞书桥退出，日志:"
    tail -8 data/feishu.log || true
    return 1
  fi
  if lsof -p "$pid" -iTCP 2>/dev/null | grep -q "feishu.cn"; then
    _log "✅ 飞书桥运行中 (WS connected, pid $pid)"
  else
    _log "⚠️ 飞书桥进程存活(pid $pid)但未见 feishu.cn 连接，确认 WS 状态"
  fi
}

_status() {
  echo "=== 镜像服务状态 ==="
  local web_pid feishu_pid
  web_pid="$(_port_pid "$WEB_PORT" || true)"
  feishu_pid="$(pgrep -f "^$VENV_PY -m llm_loop.feishu" | head -1 || true)"
  if [[ -n "$web_pid" ]]; then
    echo "web    : ✅ pid $web_pid $(curl -sf --max-time 2 "http://$WEB_HOST:$WEB_PORT/health" | head -c 20 || echo '(health 异常)')"
  else
    echo "web    : ❌ 未运行"
  fi
  if [[ -n "$feishu_pid" ]]; then
    echo "feishu : ✅ pid $feishu_pid"
  else
    echo "feishu : ❌ 未运行"
  fi
  echo "主区 web（:8902）: $(curl -sf --max-time 2 http://127.0.0.1:8902/health >/dev/null 2>&1 && echo '✅ 健康' || echo '⚠️ 未运行/不可达')"
}

case "${1:-web}" in
  web)     _stop_port "$WEB_PORT"; _start_web ;;
  feishu)  pgrep -f "^$VENV_PY -m llm_loop.feishu" | xargs -r kill 2>/dev/null || true
           sleep 2
           _start_feishu ;;
  all)     _stop_port "$WEB_PORT"
           pgrep -f "^$VENV_PY -m llm_loop.feishu" | xargs -r kill 2>/dev/null || true
           sleep 2
           _start_web && _start_feishu ;;
  status)  _status ;;
  *)       echo "用法: $0 {web|feishu|all|status}"; exit 1 ;;
esac
