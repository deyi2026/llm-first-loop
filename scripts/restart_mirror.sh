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
#   6. 自重启勿用 launchctl submit —— launchd 会把 submit 作业无限重拉
#      （2026-08-28 实证：lfl.web.restart 作业致 web 每 ~30s 循环重启、
#       web.log 累计 100 次 Shutting down；拆除 launchctl remove lfl.web.restart。
#       详见 experiences/EXPERIENCE-20260828-mirror-restart-launchd-trap.md）
#      正确自重启：直接跑本脚本 —— nohup+& 已脱离会话进程树，
#      agent shell 正常退出不清理子进程，无需 setsid/launchd。
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
# R2（RUNTIME-SOT-WIRE）: 业务配置经 runtime resolver 查询（.env 权威 + 跨区污染
# 防御——外部 shell 残留 WEB_PORT=8902 不压过镜像 .env 的 8903）。
# 修复(2026-08-29): ①查询必须带 PYTHONPATH=镜像 src——shell 环境常残留主区 PYTHONPATH
# （DSH harness 注入），不带则跑主区 resolver 对镜像语义输出空、exit 0；
# ②成功但输出为空也要兜底——$(cmd || echo x) 只兜命令失败兜不了空串成功
# （实证: WEB_PORT="" → "port 无监听进程"假停机 + 新进程绑 8903 撞旧进程 Errno 48）。
WEB_PORT="$(PYTHONPATH="$MIRROR_DIR/src" "$VENV_PY" -m llm_loop.runtime.resolver WEB_PORT 2>/dev/null || true)"
WEB_PORT="${WEB_PORT:-8903}"
WEB_HOST="$(PYTHONPATH="$MIRROR_DIR/src" "$VENV_PY" -m llm_loop.runtime.resolver WEB_HOST 2>/dev/null || true)"
WEB_HOST="${WEB_HOST:-127.0.0.1}"

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

# P1(2026-08-28) 跨区数据锚点污染防御（主区实证事故对称防护）: 清空继承锚点键,
# 由本区 .env/默认相对路径接管
# R2(2026-08-29) 补 PYTHONPATH: 主区调用侧残留 PYTHONPATH=<主区>/src 优先级高于
# venv .pth，会让镜像进程加载主区代码（跨区代码污染）；必须清空，模块解析归 venv。
# 补凭证对清理: shell 残留 FEISHU_APP_ID（主区 app）无配套 SECRET 时，进程会拼出
# "主区 app_id + 镜像 secret"错配对 → 预检 10014 app secret invalid（2026-08-29 实证:
# 旧脚本 source .env 会覆盖残留而掩盖此问题，R2 不 source 后暴露）。清空后由
# python 配置链从 .env/.feishu.env 读配套凭证对。
# 补 DATA_DIR 清理(2026-08-29 第四雷): Settings 消费的是 DATA_DIR 键（≠LFL_DATA_DIR，
# 两个不同的键！），且环境优先压过 .env——启动 shell 残留 DATA_DIR=<主区绝对路径>时
# engine 直读主区 data → 镜像 web 显示主区会话（实证 pid 97159）。清空后由 .env 的
# DATA_DIR=./data（cwd 锚定）接管。
unset LFL_DATA_DIR DSH_HOME PYTHONPATH FEISHU_APP_ID FEISHU_APP_SECRET DATA_DIR
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
  # R2: 业务配置归 python（web main 的 load_env_file，环境优先）——shell 不再
  # source .env、不再设 PYTHONPATH（R1 venv .pth 天然指向镜像 src，PYTHONPATH
  # 反而是跨区污染源）。清空继承锚点键防残留压过 .env（对齐 restart_system.sh）；
  # health check 用启动前捕获的局部变量（unset 后 $WEB_* 不再绑定，-u 会报错）。
  local check_host="$WEB_HOST" check_port="$WEB_PORT"
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  # 协议 §3 恢复(2026-08-29): 共享 venv 属主区（editable .pth 指主区 src），
  # 镜像服务必须自带 PYTHONPATH=镜像 src 自卫——不依赖 .pth 指向（.pth 被外力
  # 翻向镜像会反向破坏主区；被翻向主区则镜像加载错代码。显式注入两边都免疫，
  # 且覆盖 shell 残留的主区 PYTHONPATH）。
  PYTHONPATH="$MIRROR_DIR/src" nohup "$VENV_PY" -m llm_loop.web >> data/web.log 2>&1 &
  local pid=$!
  for _ in $(seq 1 30); do
    if curl -sf --max-time 2 "http://$check_host:$check_port/health" >/dev/null 2>&1; then
      _log "✅ web 就绪: http://$check_host:$check_port/(pid $pid)"
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
  # R2: 同 _start_web——配置归 python，shell 清锚点键防污染；
  # PYTHONPATH=镜像 src 显式注入（协议 §3，同 _start_web 注释）。
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  PYTHONPATH="$MIRROR_DIR/src" nohup "$VENV_PY" -m llm_loop.feishu >> data/feishu.log 2>&1 &
  local pid=$!
  # 校验: 预检失败会立即退出；WS 连接成功后心跳文件写 state=connected。
  # 心跳文件优先（权威；lsof 查 feishu.cn 连接有时序误报）。WS 握手含 token 获取+
  # 建链，实测 15s~55s 波动，故轮询至多 90s、连上即刻提前返回（2026-08-28 实证）。
  local _dead=0
  for _ in $(seq 1 90); do
    if ! kill -0 "$pid" 2>/dev/null; then
      _dead=1
      break
    fi
    if [[ -f "$MIRROR_DIR/data/feishu_heartbeat.json" ]] && "$VENV_PY" -c "
import json, sys
d = json.load(open('$MIRROR_DIR/data/feishu_heartbeat.json'))
sys.exit(0 if d.get('pid') == $pid and d.get('state') == 'connected' else 1)
" 2>/dev/null; then
      _log "✅ 飞书桥心跳 connected (pid $pid)"
      return 0
    fi
    sleep 1
  done
  if [[ "$_dead" == "1" ]]; then
    _log "✗ 飞书桥退出，日志:"
    tail -8 data/feishu.log || true
    return 1
  fi
  if lsof -p "$pid" -iTCP 2>/dev/null | grep -q "feishu.cn"; then
    _log "✅ 飞书桥运行中 (WS connected, pid $pid)"
  else
    _log "⚠️ 飞书桥进程存活(pid $pid)但心跳未见 connected，确认 WS 状态"
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
