#!/usr/bin/env bash
# restart_mirror.sh — 镜像工作区常驻服务重启脚本（2026-08-22 实践整理）
#
# 管理镜像的常驻服务:
#   web    FastAPI 服务（python -m llm_loop.web，端口 8903，公开就绪端点 GET /auth/status）
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
#      正确自重启（2026-09-09 修正）：
#      ① 启动通道走 execute_command 后台 job（run_in_background）——独立进程组、
#        无 30s 前台超时、宿主死亡不牵连；
#      ② 服务进程一律经 _spawn_detached（可移植 setsid）脱离调用方进程组再 exec。
#        （原判断"nohup+& 已脱离会话进程树"是错的：nohup 不换进程组，宿主 shell
#         被超时 killpg 整树 SIGKILL 时会被波及；且 macOS 无 setsid(1)，脚本内
#         `command -v setsid` 落空仍会产出假 armed 回执——2026-09-09 双实证。）
#
# 用法:
#   bash scripts/restart_mirror.sh web           # 重启 web（默认）
#   bash scripts/restart_mirror.sh feishu        # 重启飞书桥
#   bash scripts/restart_mirror.sh all           # 全部重启
#   bash scripts/restart_mirror.sh status        # 查看状态
#   # 自动化/AI 代执行（等长任务跑完 + 免交互确认，双开关缺一不可）:
#   RESTART_WAIT_IDLE=1 FORCE=1 bash scripts/restart_mirror.sh all
#
# 2026-09-09 加固（修1-修5，详见 tests/scripts/test_restart_mirror_hardening.py）:
#   修1 重启前长任务保护: web/feishu/all 分支统一 _restart_precheck——poll 飞书
#       心跳（processing_msg_id/queue_depth）至空闲；RESTART_WAIT_IDLE 超时回退
#       交互确认，FORCE=1 免确认。后台 job 非 tty 下 read 撞 EOF 必取消。
#   修2 all 分支失败补偿: web 停/启失败不再 && 短路吞掉 feishu 恢复；停止失败
#       的服务跳过启动（强启=双进程），各服务独立成败、聚合退出码。
#   修3 服务启动走 _spawn_detached（python setsid+execvp，同 PID exec）。
#   修4 每次重启回执落盘 data/restart-receipt.json（.log 追加历史）——stdout
#       回执随宿主死亡（假 armed 事故），落盘是唯一可独立核查载体:
#       cat data/restart-receipt.json
#   修5 停止判定源: web=端口 lsof∪argv 且等 PID 本身退出；feishu=心跳 pid
#       （≤180s 新鲜度门，防 PID 复用误杀）∪ argv 兜底（uv 启动会改写 argv）。
#       xargs kill 裸杀路径已废除。

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
# RESTART_PORT: 冻结端口值——_start_web/_start_feishu 内部会 unset WEB_PORT/WEB_HOST
# （防启动 shell 残留值压过 .env），但 case 分支与回执在启动之后仍需端口值
# （set -u 下引用已 unset 变量会中断脚本）。独立变量在 top-level 冻结，不受影响。
RESTART_PORT="$WEB_PORT"

_log() { echo "[mirror] $(date '+%H:%M:%S') $*"; }

# ── 重启前长任务保护（修1, 2026-09-09 移植自 restart_system.sh；判源改 VENV_PY）──
# RESTART_WAIT_IDLE=1 → poll 心跳至空闲再停机；超时回退交互确认（FORCE=1 跳过交互）。
# 自动化纪律：后台 job 非 tty 下 read 撞 EOF 必取消——AI 代执行必须双开
# RESTART_WAIT_IDLE=1 FORCE=1（缺一不可）。
_heartbeat_busy() {
  "$VENV_PY" -c "
import json
try:
    d = json.load(open('$MIRROR_DIR/data/feishu_heartbeat.json'))
except Exception:
    raise SystemExit(0)
mid = (d.get('processing_msg_id') or '').strip()
q = d.get('queue_depth') or 0
try:
    q = int(q)
except Exception:
    q = 0
parts = []
if mid:
    parts.append('processing:' + mid[:12])
if q > 0:
    parts.append('queue:%d' % q)
if parts:
    print(' '.join(parts))
" 2>/dev/null
}
_restart_precheck() {
  local waited=0 busy
  if [[ "${RESTART_WAIT_IDLE:-0}" == "1" ]]; then
    local idle_timeout="${RESTART_WAIT_IDLE_TIMEOUT_S:-300}" idle_poll="${RESTART_WAIT_IDLE_POLL_S:-5}"
    while :; do
      busy="$(_heartbeat_busy)"
      if [[ -z "$busy" ]]; then
        (( waited > 0 )) && _log "飞书桥已空闲（等待 ${waited}s），继续重启"
        return 0
      fi
      if (( waited >= idle_timeout )); then
        _log "等待空闲超时（${waited}s ≥ ${idle_timeout}s），回退确认流程"
        break
      fi
      _log "飞书桥忙（${busy}），等待任务完成（${waited}/${idle_timeout}s）..."
      sleep "$idle_poll"
      (( waited += idle_poll ))
    done
  fi
  busy="$(_heartbeat_busy)"
  [[ -z "$busy" ]] && return 0
  _log "⚠️ 飞书桥忙（${busy}）——重启会中断该任务且无回复。"
  if [[ "${FORCE:-0}" == "1" ]]; then
    _log "FORCE=1：跳过交互确认，强制继续（自动化模式，责任在调用方）"
    return 0
  fi
  echo -n "确认继续重启? (y/N) "
  read -r ans
  if [[ ! "$ans" =~ ^[yY]$ ]]; then
    _log "已取消重启（保护进行中的长任务）。"
    exit 1
  fi
}

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

# 按端口找监听进程（只识别目标端口；不会碰主区 8902）。
_port_pid() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}'
}

# 镜像 Web 还可能在收到 SIGTERM 后先释放监听端口、但进程本身继续存活并持有
# <session>.run.lock。只等端口释放会错误地启动第二个 Web，之后所有新请求都被旧
# run owner 判成“另一进程执行”。用镜像 venv 的绝对 argv 精确识别本区 Web，既能
# 找到已经不监听的 stale owner，也不会误杀主区不同 venv 的 :8902。
_mirror_web_pids() {
  pgrep -f "^${VENV_PY} -m llm_loop\.web( |$)" 2>/dev/null || true
}

_pid_alive() {
  kill -0 "$1" 2>/dev/null
}

_stop_web() {
  local port="$1" listener pids pid survivors
  listener="$(_port_pid "$port" || true)"
  pids="$(_mirror_web_pids || true)"
  if [[ -n "$listener" ]]; then
    pids="$(printf '%s\n%s\n' "$pids" "$listener" | awk 'NF && !seen[$1]++ {print $1}')"
  fi
  if [[ -z "$pids" ]]; then
    _log "port $port 无镜像 Web 进程"
    return 0
  fi

  _log "停止镜像 Web pid(s): $(echo "$pids" | tr '\n' ' ') (port $port)..."
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
  done <<< "$pids"

  # 关键：等待 PID 本身退出，而不是只看端口。旧进程释放端口但仍持 run lease
  # 仍属于未停止状态。
  for _ in $(seq 1 20); do
    survivors=""
    while IFS= read -r pid; do
      if [[ -n "$pid" ]] && _pid_alive "$pid"; then
        survivors+="${pid} "
      fi
    done <<< "$pids"
    [[ -z "$survivors" ]] && break
    sleep 0.5
  done

  if [[ -n "${survivors:-}" ]]; then
    _log "10s 后仍有旧 PID 存活，强制 kill: $survivors"
    for pid in $survivors; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    for _ in $(seq 1 30); do
      survivors=""
      for pid in $pids; do
        _pid_alive "$pid" && survivors+="${pid} " || true
      done
      [[ -z "$survivors" ]] && break
      sleep 0.1
    done
  fi

  if [[ -n "${survivors:-}" ]]; then
    _log "✗ 旧镜像 Web PID 仍未退出，拒绝启动新进程: $survivors"
    return 1
  fi
  if [[ -n "$(_port_pid "$port" || true)" ]]; then
    _log "✗ port $port 仍被占用，拒绝启动新进程"
    return 1
  fi
  _log "已停止（旧 PID 全部退出）"
}

# ── 可移植进程脱离（修3, 2026-09-09）──
# macOS 无 setsid(1)（实证：`command -v setsid` 落空 → watchdog 假 armed 回执）。
# nohup 不换进程组：宿主 shell 被 execute_command 超时 killpg 整树 SIGKILL 时，
# 普通 `nohup cmd &` 同组会被波及。python 中间进程 setsid() 后 execvp——同 PID
# 换入目标程序，新会话/新进程组，killpg 不可达，调用方死亡亦不牵连。
# 启动通道纪律：自重启优先 execute_command 后台 job（run_in_background，无 30s 超时）。
_spawn_detached() {
  local logfile="$1"; shift
  "$VENV_PY" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" >>"$logfile" 2>&1 &
}

# ── 飞书桥判定/停止（修5 判定源: 心跳 pid 优先，2026-09-09）──
# 飞书桥无端口锚点——心跳文件 pid 为权威（写心跳者即进程本人）；须新鲜度门
# （≤180s）防 PID 复用误杀无辜进程；pgrep argv 仅兜底（实证：本服务可经 uv
# 启动改写 argv 为 "python3.1 ..."，pgrep 对其天然盲，2026-09-09）。
_feishu_pids() {
  local hb="$MIRROR_DIR/data/feishu_heartbeat.json"
  local hb_pid="" hb_mtime now
  if [[ -f "$hb" ]]; then
    hb_mtime="$(stat -f %m "$hb" 2>/dev/null || stat -c %Y "$hb" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    if (( now - hb_mtime <= 180 )); then
      hb_pid="$("$VENV_PY" -c "
import json
try: print(json.load(open('$hb')).get('pid') or '')
except Exception: pass" 2>/dev/null || true)"
    fi
  fi
  { [[ -n "$hb_pid" ]] && echo "$hb_pid"; pgrep -f "^$VENV_PY -m llm_loop\.feishu( |$)" 2>/dev/null || true; } | awk 'NF && !seen[$1]++ {print $1}'
}
_feishu_stop() {
  local pids pid survivors
  pids="$(_feishu_pids || true)"
  if [[ -z "$pids" ]]; then
    _log "无飞书桥进程（心跳 pid + argv 均未命中）"
    return 0
  fi
  _log "停止飞书桥 pid(s): $(echo "$pids" | tr '\n' ' ')..."
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
  done <<< "$pids"
  for _ in $(seq 1 20); do
    survivors=""
    while IFS= read -r pid; do
      [[ -n "$pid" ]] && _pid_alive "$pid" && survivors+="${pid} "
    done <<< "$pids"
    [[ -z "$survivors" ]] && break
    sleep 0.5
  done
  if [[ -n "${survivors:-}" ]]; then
    _log "10s 后仍存活，强制 kill: $survivors"
    for pid in $survivors; do
      kill -KILL "$pid" 2>/dev/null || true
    done
    for _ in $(seq 1 30); do
      survivors=""
      for pid in $pids; do
        _pid_alive "$pid" && survivors+="${pid} " || true
      done
      [[ -z "$survivors" ]] && break
      sleep 0.1
    done
  fi
  if [[ -n "${survivors:-}" ]]; then
    _log "✗ 飞书桥 PID 仍未退出: $survivors"
    return 1
  fi
  _log "飞书桥已停止"
}

# ── 回执落盘（修4, 2026-09-09）──
# 实证教训：上轮"watchdog armed, pgid=18559"回执只活在 stdout——载体随宿主死亡，
# 回执无处验证。落盘是唯一可独立核查的载体（设计本身正确，并入脚本）。
RECEIPT_JSON="$MIRROR_DIR/data/restart-receipt.json"   # 最新一次（覆盖）
RECEIPT_LOG="$MIRROR_DIR/data/restart-receipt.log"     # 历史（追加）
_write_receipt() {
  local action="$1" rc="$2" detail="${3:-}"
  local head web_pid feishu_pid
  head="$(git -C "$MIRROR_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
  web_pid="$(_port_pid "$RESTART_PORT" || true)"
  feishu_pid="$(_feishu_pids 2>/dev/null | head -1 || true)"
  "$VENV_PY" - "$RECEIPT_JSON" "$RECEIPT_LOG" "$action" "$rc" "$head" "$detail" "$web_pid" "$feishu_pid" <<'PY' 2>/dev/null || { _log "⚠️ 回执落盘失败（不影响服务状态）"; return 0; }
import datetime, json, sys
jpath, lpath, action, rc, head, detail, web_pid, feishu_pid = sys.argv[1:9]
rec = {
    "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "action": action,
    "rc": int(rc),
    "git_head": head,
    "web_pid": int(web_pid) if web_pid.strip().isdigit() else None,
    "feishu_pid": int(feishu_pid) if feishu_pid.strip().isdigit() else None,
    "detail": detail,
}
line = json.dumps(rec, ensure_ascii=False)
with open(jpath, "w") as f:
    f.write(line + "\n")
with open(lpath, "a") as f:
    f.write(line + "\n")
PY
  _log "回执已落盘: $RECEIPT_JSON (rc=$rc)"
}

_start_web() {
  _log "启动 web(port $WEB_PORT)..."
  _prep_dsh_env
  # R2: 业务配置归 python（web main 的 load_env_file，环境优先）——shell 不再
  # source .env、不再设 PYTHONPATH（R1 venv .pth 天然指向镜像 src，PYTHONPATH
  # 反而是跨区污染源）。清空继承锚点键防残留压过 .env（对齐 restart_system.sh）；
  # readiness check 用公开 /auth/status；/health 在 WEB_AUTH_REQUIRE=1 时按设计需要认证。
  # 检查仍用启动前捕获的局部变量（unset 后 $WEB_* 不再绑定，-u 会报错）。
  local check_host="$WEB_HOST" check_port="$WEB_PORT"
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  # 协议 §3 恢复(2026-08-29): 共享 venv 属主区（editable .pth 指主区 src），
  # 镜像服务必须自带 PYTHONPATH=镜像 src 自卫——不依赖 .pth 指向（.pth 被外力
  # 翻向镜像会反向破坏主区；被翻向主区则镜像加载错代码。显式注入两边都免疫，
  # 且覆盖 shell 残留的主区 PYTHONPATH）。
  # 修3(2026-09-09): 启动改走 _spawn_detached（可移植 setsid+execvp）——nohup+&
  # 不换进程组，宿主 shell 超时 killpg 会被整树波及（execute_command.py:108-109 实证）。
  PYTHONPATH="$MIRROR_DIR/src" _spawn_detached data/web.log "$VENV_PY" -m llm_loop.web
  local pid=$!
  for _ in $(seq 1 30); do
    if curl -sf --max-time 2 "http://$check_host:$check_port/auth/status" >/dev/null 2>&1; then
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
  # 修3(2026-09-09): 同 _start_web——经 _spawn_detached 脱离进程组再 exec。
  PYTHONPATH="$MIRROR_DIR/src" _spawn_detached data/feishu.log "$VENV_PY" -m llm_loop.feishu
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
  # 修5(2026-09-09): 判定源换 _feishu_pids（心跳 pid 优先 ∪ argv 兜底，uv 改写 argv 场景不再盲）
  feishu_pid="$(_feishu_pids 2>/dev/null | head -1 || true)"
  if [[ -n "$web_pid" ]]; then
    echo "web    : ✅ pid $web_pid $(curl -sf --max-time 2 "http://$WEB_HOST:$WEB_PORT/auth/status" | head -c 80 || echo '(readiness 异常)')"
  else
    echo "web    : ❌ 未运行"
  fi
  if [[ -n "$feishu_pid" ]]; then
    echo "feishu : ✅ pid $feishu_pid (hb: $("$VENV_PY" -c "import json;print(json.load(open('$MIRROR_DIR/data/feishu_heartbeat.json')).get('state','-'))" 2>/dev/null || echo '?'))"
  else
    echo "feishu : ❌ 未运行"
  fi
  echo "主区 web（:8902）: $(curl -sf --max-time 2 http://127.0.0.1:8902/health >/dev/null 2>&1 && echo '✅ 健康' || echo '⚠️ 未运行/不可达')"
}

case "${1:-web}" in
  web)     _restart_precheck
           _rc=0
           if ! _stop_web "$RESTART_PORT"; then
             _rc=1
             _log "web 停止失败，跳过启动（防双进程）"
           else
             _start_web || _rc=1
           fi
           _write_receipt web "$_rc" "port=$RESTART_PORT"
           exit "$_rc" ;;
  feishu)  _restart_precheck
           _rc=0
           if ! _feishu_stop; then
             _rc=1
             _log "feishu 停止失败，跳过启动"
           else
             _start_feishu || _rc=1
           fi
           _write_receipt feishu "$_rc" ""
           exit "$_rc" ;;
  all)     _restart_precheck
           # 修2(2026-09-09): 失败补偿——web 停/启失败不再 && 短路吞掉 feishu 恢复；
           # 各服务按自身停止成败独立决定是否重启（停失败强启=制造双进程，禁止）。
           _rc=0; _web_stopped=0; _feishu_stopped=0
           _stop_web "$RESTART_PORT" && _web_stopped=1 || _rc=1
           _feishu_stop && _feishu_stopped=1 || _rc=1
           if [[ "$_web_stopped" -eq 1 ]]; then
             _start_web || _rc=1
           else
             _log "web 停止失败，跳过其启动（防双进程）"
           fi
           if [[ "$_feishu_stopped" -eq 1 ]]; then
             _start_feishu || _rc=1
           else
             _log "feishu 停止失败，跳过其启动"
           fi
           _write_receipt all "$_rc" "web_stopped=$_web_stopped feishu_stopped=$_feishu_stopped"
           exit "$_rc" ;;
  status)  _status ;;
  *)       echo "用法: $0 {web|feishu|all|status}"; exit 1 ;;
esac
