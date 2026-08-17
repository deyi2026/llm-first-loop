#!/usr/bin/env bash
# llm-first-loop 系统级优雅重启脚本（M46 补充，2026-08-11）
#
# 管理常驻服务（cli 交互式，纳入 status/stop + 可启动校验，不参与常驻 start_all）:
#   web    FastAPI 服务（python -m llm_loop.web，健康端点 GET /health）
#   feishu 飞书桥（python -m llm_loop.feishu，WS 长连接）
#   cli    终端 CLI（python -m llm_loop.cli，交互式需 tty，不能后台守护）
#          cli start = 可启动性校验（import+版本）+ 提示手动终端启动（不伪装常驻）
#
# 用法:
#   scripts/restart_system.sh                  # 全部重启（web+feishu）
#   scripts/restart_system.sh start|stop|restart|status
#   scripts/restart_system.sh web|feishu|cli start|stop|restart|status   # 单服务
#
# 设计要点:
#   1. 优雅停机: SIGTERM → GRACE_S 内自然退出 → 超时 SIGKILL（每服务独立）。
#   2. 健康检查: web 用 HTTP GET /health；feishu 用看门狗心跳文件新鲜度（M47，替代易误报的 TCP 检查）；
#      cli 用进程存活（无健康端点，交互式）。
#   3. 凭证不硬编码: 环境变量优先 → 回退 本地既有实现/.env（脱敏提示不落盘）。
#   4. 端口冲突检测: web 默认 8902（被占用时经 WEB_PORT 覆盖），启动前探测。
#   5. 幂等安全: PID 文件 + pgrep 双校验；按依赖序启动（web 先、feishu 后）。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

VENV_PY="$PROJECT_DIR/.venv/bin/python"
DATA_DIR="$PROJECT_DIR/data"
WS_HOST="msg-frontier.feishu.cn"

# P0: 维护标记（restart 期间 touch，guard 检测到则跳过本轮拉起，防竞态抢跑）
MAINTENANCE_LOCK="$DATA_DIR/maintenance.lock"

# P0: trap 兜底清理维护锁（脚本中断/异常退出时防 lock 残留导致 guard 瘫痪数小时）
# 仅在 _MAINTENANCE_LOCK_ACTIVE=1 时清理：
#   restart 流程：创建 lock 时置 1，正常删除 lock 时置 0 → 异常中断 trap 清理
#   stop 流程：_stop_all 置 1，stop 命令末尾显式置 0 保留 lock 防 guard 拉起已停止服务
_MAINTENANCE_LOCK_ACTIVE=0
_cleanup_maintenance_lock() {
  if [[ "$_MAINTENANCE_LOCK_ACTIVE" -eq 1 ]]; then
    rm -f "$MAINTENANCE_LOCK" 2>/dev/null || true
  fi
}
trap _cleanup_maintenance_lock EXIT INT TERM

# 可调参数（env 覆盖）
GRACE_S="${SYSTEM_GRACE_S:-15}"                  # 优雅停机等待秒数
STARTUP_WAIT_S="${SYSTEM_STARTUP_WAIT_S:-20}"    # 启动健康检查等待秒数
STARTUP_POLL_S="${SYSTEM_STARTUP_POLL_S:-2}"     # 健康检查轮询间隔
WEB_HOST="${WEB_HOST:-127.0.0.1}"                # web 绑定地址
WEB_PORT="${WEB_PORT:-8902}"                     # web 端口（与 本地既有实现 冲突时覆盖）

_log() { printf '[restart_system] %s\n' "$*"; }
_die() { printf '[restart_system] ERROR: %s\n' "$*" >&2; exit 1; }

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


_load_llm() {
  # 通用配置从项目 .env 加载（环境变量优先，已设置的键不覆盖）——
  # 修复 M61: HISTORY_MAX_CHARS 等 .env 配置此前从未注入进程（默认 1M 预算 →
  # 上下文可膨胀至 60 万字符 → 所有模型超限/超时）
  local env_file="$PROJECT_DIR/.env"
  if [[ -f "$env_file" ]]; then
    while IFS='=' read -r _key _val; do
      _key="${_key//[$'\r']/}"
      [[ "$_key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      # 行内注释剥离（与 config.load_env_file EVO-ba4a107c 一致）：
      # 防 `KEY=1  # 注释` 把注释带进值 → export 后 _env_bool 解析非法回退默认
      _val="${_val%% #*}"
      # 去尾随空白（EVO-20260817-69d034c7 实测）：`.env` 值 `KEY=v  # 注释` 经
      # `%% #*` 剥后仍留尾随空格（`KEY=v  `）→ bash 子进程/测试直读 os.environ
      # 拿到带空格模型名 → 注册表 resolve 失败/API 400。python 层 load_settings
      # 有 strip 兜底，但 bash 注入路径（run_real_smoke.sh/测试 fixture）没有。
      _val="${_val%"${_val##*[![:space:]]}"}"
      # 密钥类键保留环境优先（允许显式 export 覆盖）；其余 .env 配置键强制生效，
      # 防外层 shell 残留脏值（如 RETRIEVE_TIMEOUT_S="1  # 注释"）遮蔽 .env 新值
      case "$_key" in
        LLM_API_KEY|LLM_BASE_URL|LLM_MODEL|DEEPSEEK_API_KEY|FEISHU_APP_ID|FEISHU_APP_SECRET)
          if [[ -z "${!_key:-}" ]]; then
            export "$_key=${_val}"
          fi
          ;;
        *)
          export "$_key=${_val}"
          ;;
      esac
    done < <(grep -vE '^\s*#|^\s*$' "$env_file")
  fi
  export LLM_API_KEY="${LLM_API_KEY:-${DEEPSEEK_API_KEY:-}}"
  export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com/v1}"
  export LLM_MODEL="${LLM_MODEL:-deepseek-v4-flash}"
  export SUMMARY_MODE="${SUMMARY_MODE:-sync}"      # EVO-20260811: 压缩主动化 LLM 摘要
  export TOOL_SCHEMA_LAZY="${TOOL_SCHEMA_LAZY:-1}" # EVO-20260811: 工具 Schema 懒加载
  if [[ -z "$LLM_API_KEY" ]]; then
    _die "LLM_API_KEY / DEEPSEEK_API_KEY 未配置"
  fi
}

# ── 进程定位（PID 文件 + pgrep 双校验，防误杀）──
_service_pid() {
  local svc="$1"
  local pid_file="$DATA_DIR/${svc}.pid"
  local pid=""
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%s' "$pid"
      return 0
    fi
  fi
  pid="$(pgrep -f "llm_loop\\.${svc}" | head -1 || true)"
  printf '%s' "$pid"
}

# ── 优雅停止单个服务（停所有匹配进程，防多进程残留）──
_stop_service() {
  local svc="$1"
  local pattern="llm_loop\\.${svc}"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -z "$pids" ]]; then
    _log "[${svc}] 未运行，跳过停止"
    rm -f "$DATA_DIR/${svc}.pid"
    return 0
  fi
  _log "[${svc}] 停止进程 $(echo "$pids" | tr '\n' ' ')（SIGTERM，等待 ${GRACE_S}s）..."
  # P2: 停所有匹配进程（防多进程残留），逐个 SIGTERM
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done
  local waited=0
  while pgrep -f "$pattern" >/dev/null 2>&1 && (( waited < GRACE_S )); do
    sleep 1
    (( waited += 1 ))
  done
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    _log "[${svc}] 超时未退出，SIGKILL 强杀"
    pkill -9 -f "$pattern" 2>/dev/null || true
    sleep 1
  else
    _log "[${svc}] 已优雅退出（${waited}s）"
  fi
  rm -f "$DATA_DIR/${svc}.pid"
}

# ── 运行日志轮转（P1-3: 防无限增长；超阈值轮转为 .1，保留一个旧档）──
LOG_MAX_MB="${SYSTEM_LOG_MAX_MB:-20}"
_rotate_log() {
  local log="$1"
  [[ -f "$log" ]] || return 0
  local size_mb
  size_mb="$(du -m "$log" 2>/dev/null | cut -f1)"
  [[ -z "$size_mb" || "$size_mb" -lt "$LOG_MAX_MB" ]] && return 0
  mv "$log" "$log.1" 2>/dev/null && _log "日志轮转: $log (${size_mb}MB ≥ ${LOG_MAX_MB}MB) → $log.1"
}

# ── 单服务健康检查（返回 0=健康）──
_health_check() {
  local svc="$1"
  local pid="$2"
  case "$svc" in
    web)
      # HTTP 探活 /health（30s 超时；进程死/请求失败均判不健康）
      if ! kill -0 "$pid" 2>/dev/null; then return 1; fi
      curl -sf --max-time 5 "http://${WEB_HOST}:${WEB_PORT}/health" >/dev/null 2>&1
      ;;
    feishu)
      # M47：健康 = 进程存活 + 看门狗心跳新鲜（心跳文件 90s 内更新）。
      # 旧版只看 TCP ESTABLISHED，SDK 锁泄漏假死时 TCP 不断 → 误报健康（2026-08-12 事故）。
      # 心跳文件缺失（旧进程未升级）→ 如实判不健康，提示重启接入新防护。
      if ! kill -0 "$pid" 2>/dev/null; then return 1; fi
      local hb="$DATA_DIR/feishu_heartbeat.json"
      [[ -f "$hb" ]] || return 1
      local hb_mtime now_s
      hb_mtime="$(stat -f %m "$hb" 2>/dev/null || stat -c %Y "$hb" 2>/dev/null || echo 0)"
      now_s="$(date +%s)"
      (( now_s - hb_mtime <= 90 ))
      ;;
    cli)
      # cli 无健康端点（交互式终端程序）：进程存活即健康
      kill -0 "$pid" 2>/dev/null
      ;;
    *) return 1 ;;
  esac
}

# ── 启动单个服务（含健康检查，失败如实报告）──
_start_service() {
  local svc="$1"
  local running_pid
  running_pid="$(_service_pid "$svc")"
  if [[ -n "$running_pid" ]]; then
    _log "[${svc}] 已在运行（PID ${running_pid}），无需启动"
    # P2: 回写 PID 文件（防"已运行"分支导致 PID 文件缺失，后续退化为不可靠 pgrep）
    echo "$running_pid" > "$DATA_DIR/${svc}.pid"
    return 0
  fi
  _load_credentials
  _load_llm

  # DSH 编排（2026-08-16）：DSH_HOME 重定向到项目内 data/dsh-home（服务进程对 data/ 有写
  # 权限）——规避 macOS TCC/沙箱对 ~/.dsh 的写入授权限制（dsh_task 真实调用依赖该目录可写；
  # 凭据仍共享 ~/.dsh/.credentials.yaml，仅 profile/session 落盘到项目内）
  # 运行簿（升级/清理/出错恢复）: docs/local/DSH-INTEGRATION-RUNBOOK-20260816.md
  export DSH_HOME="${DSH_HOME:-$PROJECT_DIR/data/dsh-home}"
  mkdir -p "$DSH_HOME"

  case "$svc" in
    web)
      # 端口冲突检测（被占用 → 如实提示用 WEB_PORT 覆盖，不静默抢端口）
      if lsof -iTCP:"${WEB_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        _die "[web] 端口 ${WEB_PORT} 已被占用（可用 WEB_PORT=xxxx 覆盖）"
      fi
      _rotate_log "$DATA_DIR/web.log"
      _log "[web] 启动 FastAPI（${WEB_HOST}:${WEB_PORT}，日志: ${DATA_DIR}/web.log）..."
      nohup "$VENV_PY" -m llm_loop.web >> "$DATA_DIR/web.log" 2>&1 &
      ;;
    feishu)
      _rotate_log "$DATA_DIR/feishu_bridge.log"
      # P1-3-R2: 注入优雅退出时间契约（wait+drain ≤ GRACE_S−余量；10+3=13 ≤ 15，env 可覆盖）
      export FEISHU_EXIT_WAIT_S="${FEISHU_EXIT_WAIT_S:-10}"
      export FEISHU_EXIT_DRAIN_S="${FEISHU_EXIT_DRAIN_S:-3}"
      _log "[feishu] 启动飞书桥（日志: ${DATA_DIR}/feishu_bridge.log）..."
      nohup "$VENV_PY" -m llm_loop.feishu >> "$DATA_DIR/feishu_bridge.log" 2>&1 &
      ;;
    cli)
      # cli 是交互式终端程序（需 tty），不能 nohup 后台常驻——只做可启动性校验并提示手动启动。
      # 校验: import 引擎 + 打印当前 git HEAD（保证 cli 与脚本同代码基线）。
      _log "[cli] 校验可启动性（import llm_loop.cli + 当前代码 HEAD）..."
      if ! "$VENV_PY" -c "import llm_loop.cli; print('import OK')" >/dev/null 2>&1; then
        _log "[cli] ❌ import 失败（venv/代码异常），详见上方错误"
        return 1
      fi
      _log "[cli] import OK；当前代码 $(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
      _log "[cli] 交互式程序需 tty，请手动终端启动: $VENV_PY -m llm_loop.cli [--interactive]（脚本不做后台常驻）"
      echo "$VENV_PY -m llm_loop.cli --interactive" > "$DATA_DIR/cli.start.hint"  # 提示落盘可查
      return 0
      ;;
    *) _die "未知服务: ${svc}" ;;
  esac

  local new_pid=$!
  echo "$new_pid" > "$DATA_DIR/${svc}.pid"
  _log "[${svc}] 新进程 PID ${new_pid}，健康检查（${STARTUP_WAIT_S}s 超时）..."

  local waited=0
  while (( waited < STARTUP_WAIT_S )); do
    if ! kill -0 "$new_pid" 2>/dev/null; then
      rm -f "$DATA_DIR/${svc}.pid"
      _die "[${svc}] 进程启动即退出（详见 ${DATA_DIR}/${svc}.log 尾部）"
    fi
    if _health_check "$svc" "$new_pid"; then
      _log "[${svc}] 健康检查通过 ✓"
      return 0
    fi
    sleep "$STARTUP_POLL_S"
    (( waited += STARTUP_POLL_S ))
  done
  # 超时：进程存活但未就绪 → 保留进程并如实提示（不静默宣称成功）
  _log "[${svc}] 警告: ${STARTUP_WAIT_S}s 内健康检查未通过（进程仍在，检查 ${DATA_DIR}/${svc}.log）"
  return 0
}

# ── 单服务状态 ──
_status_service() {
  local svc="$1"
  local pid="$(_service_pid "$svc")"
  if [[ -z "$pid" ]]; then
    _log "[${svc}] 未运行"
    return 0
  fi
  if _health_check "$svc" "$pid"; then
    _log "[${svc}] 运行中: PID ${pid}（健康）"
  else
    _log "[${svc}] 运行中: PID ${pid}（健康检查未通过）"
  fi
}

# ── 服务集定义 ──
SERVICES="web feishu cli"
WEB_BEFORE_FEISHU="web feishu"   # 启动序：web 先（依赖 LLM/端口）；cli 交互式不参与常驻启动
FEISHU_BEFORE_WEB="feishu web"   # 停止序：feishu 先（桥先断，web 后）

# ── 重启前检测（2026-08-16）：长任务处理中 → 警告确认，防重启打断导致无反馈 ──
_restart_precheck() {
  local mid
  mid="$(python3 -c "
import json
p = '$DATA_DIR/feishu_heartbeat.json'
try:
    d = json.load(open(p))
    print(d.get('processing_msg_id', '') or '')
except Exception:
    print('')
" 2>/dev/null)"
  if [[ -n "$mid" ]]; then
    echo "[restart_system] ⚠️ 飞书桥正在处理消息 ${mid:0:12}（长任务进行中）——重启会中断该任务且无回复。"
    echo -n "确认继续重启? (y/N) "
    read -r ans
    if [[ ! "$ans" =~ ^[yY]$ ]]; then
      echo "[restart_system] 已取消重启（保护进行中的长任务）。"
      exit 1
    fi
  fi
}

# ── 全部停止（逆启动序，逐个优雅停机）──
_stop_all() {
  # P0: 维护标记（重启期间 guard 跳过拉起，防竞态抢跑）
  touch "$MAINTENANCE_LOCK"
  _MAINTENANCE_LOCK_ACTIVE=1
  for svc in $FEISHU_BEFORE_WEB; do
    _stop_service "$svc"
  done
}

# ── 全部启动（正启动序，逐个健康检查）──
_start_all() {
  for svc in $WEB_BEFORE_FEISHU; do
    _start_service "$svc"
  done
  rm -f "$MAINTENANCE_LOCK"  # P0: 重启完成，恢复 guard
  _MAINTENANCE_LOCK_ACTIVE=0
  # 2026-08-16: 工作区变更闭环——重启生效后 ack（清 flag + 刷新基线）
  if [[ -f "$PROJECT_DIR/scripts/guard_system.sh" ]]; then
    bash "$PROJECT_DIR/scripts/guard_system.sh" ack-workspace 2>/dev/null || true
  fi
  # 2026-08-16: 重启后一键验证（对齐孤儿进程排查经验）——每服务 pgrep 应恰好 1 行、
  # web 端口监听应单一 PID；多实例残留如实告警（fail-open 不阻断，防旧连接抢消息）
  _verify_single_instance
}

# ── 重启后验证（防多实例残留：健康检查只看主 PID，残留进程会抢端口/抢飞书消息）──
_verify_single_instance() {
  local svc pids count port_pids
  for svc in $SERVICES; do
    pids="$(pgrep -f "llm_loop\\.${svc}" || true)"
    count="$(printf '%s\n' "$pids" | grep -c . || true)"
    if [[ -n "$pids" ]] && (( count > 1 )); then
      _log "[${svc}] ⚠️ 检测到 ${count} 个实例（残留）: $(echo "$pids" | tr '\n' ' ')。建议手动清理: pkill -f 'llm_loop\\.${svc}' 后重跑 restart"
    else
      _log "[${svc}] 实例数 ${count} ✓"
    fi
  done
  # web 端口单一监听校验
  port_pids="$(lsof -tiTCP:"${WEB_PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    count="$(printf '%s\n' "$port_pids" | grep -c . || true)"
    if (( count > 1 )); then
      _log "[web] ⚠️ 端口 ${WEB_PORT} 有 ${count} 个监听者（残留）: $(echo "$port_pids" | tr '\n' ' ')"
    else
      _log "[web] 端口 ${WEB_PORT} 单一监听 ✓"
    fi
  fi
}

# ── 全部状态 ──
_status_all() {
  for svc in $SERVICES; do
    _status_service "$svc"
  done
}

# ── 主入口：支持 [service] action 与全局 action ──
ACTION="${2:-}"
case "${1:-}" in
  web|feishu|cli)
    [[ -n "$ACTION" ]] || ACTION="restart"
    case "$ACTION" in
      start)   _start_service "$1" ;;
      stop)    _stop_service "$1" ;;
      restart) touch "$MAINTENANCE_LOCK"; _MAINTENANCE_LOCK_ACTIVE=1; _stop_service "$1"; _start_service "$1"; rm -f "$MAINTENANCE_LOCK"; _MAINTENANCE_LOCK_ACTIVE=0 ;;
      status)  _status_service "$1" ;;
      *)       _die "未知命令: ${ACTION}（支持 start/stop/restart/status）" ;;
    esac
    ;;
  start)   _start_all ;;
  stop)    _stop_all; _MAINTENANCE_LOCK_ACTIVE=0 ;;  # stop 故意保留 lock 防 guard 拉起
  restart) _restart_precheck; _stop_all; _start_all ;;  # precheck: 长任务处理中警告确认
  status)  _status_all ;;
  *)       _die "用法: $0 [web|feishu] [start|stop|restart|status] 或 $0 [start|stop|restart|status]" ;;
esac