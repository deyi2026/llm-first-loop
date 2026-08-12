#!/usr/bin/env bash
# 常驻服务守护脚本（P1-3-R4，2026-08-12）
#
# 职责（RULE-AI-00 程序最小化：只做"检测 + 拉起 + 记录"，无编排、无业务决策）:
#   - 检测 web/feishu 是否健康（复用 restart_system.sh status 幂等入口）
#   - 不健康 → restart_system.sh <svc> start 自动拉起（幂等：已在运行则跳过，不误杀）
#   - 连续失败指数退避（20→40→80→160→上限 300s）防重启风暴
#   - flock 锁 data/guard.lock 防多实例（launchd 反复拉起时只留一个）
#   - 动作日志 data/guard.log（时刻/PID/动作/原因，AI/人工可复核）
# 守护自身由 launchd plist（com.user.llm-loop-guard）KeepAlive 管理。
#
# 用法:
#   scripts/guard_system.sh          # 守护循环（前台，供 launchd/nohup 管理）
#   scripts/guard_system.sh once     # 单次检测+拉起（测试/手动）
#   scripts/guard_system.sh status   # 守护自身状态（PID/日志尾部）

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DATA_DIR="$PROJECT_DIR/data"
GUARD_LOG="$DATA_DIR/guard.log"

RESTART_SCRIPT="$PROJECT_DIR/scripts/restart_system.sh"

# 可调参数（env 覆盖）
GUARD_POLL_S="${GUARD_POLL_S:-20}"                 # 检测周期
GUARD_MAX_BACKOFF_S="${GUARD_MAX_BACKOFF_S:-300}"  # 退避上限
GUARD_BACKOFF_BASE_S="${GUARD_BACKOFF_BASE_S:-20}" # 退避基数（20→40→80→160→上限）

_log_guard() {
  # _log_guard <action> <svc> <detail>
  local ts
  ts="$(date '+%Y-%m-%dT%H:%M:%S')"
  printf '%s pid=%s action=%s svc=%s detail=%s\n' \
    "$ts" "$$" "$1" "${2:-}" "${3:-}" >> "$GUARD_LOG" 2>/dev/null || true
}

# ── 防多实例（mkdir 原子锁：POSIX 兼容，macOS 无 flock 命令）──
# 持有锁目录即单实例；拿到锁的实例退出前释放（trap）。launchd 反复拉起时仅一个存活。
_LOCK_DIR="$DATA_DIR/guard.lock"
if [[ -f "$_LOCK_DIR" ]]; then
  rm -f "$_LOCK_DIR"  # 一次性清理旧 flock 遗留文件（防 mkdir 失败）
fi
if ! mkdir "$_LOCK_DIR" 2>/dev/null; then
  exit 0  # 已有实例持有锁 → 本实例退出（防多实例）
fi
trap 'rmdir "$_LOCK_DIR" 2>/dev/null || true' EXIT

# ── 服务健康检测（复用 restart_system.sh status 输出判健康）──
# 输出格式: "运行中: PID x（健康）" = 健康；"运行中: PID x（健康检查未通过）" = 不健康。
# 仅匹配"（健康）"精确后缀，避免"健康检查未通过"误判为健康。
_service_healthy() {
  local svc="$1"
  local out
  out="$("$RESTART_SCRIPT" "$svc" status 2>&1 || true)"
  case "$out" in
    *"（健康）"*) return 0 ;;
    *) return 1 ;;
  esac
}

# ── 拉起服务（不健康时强制 restart：stop + start 幂等，避免"已在运行"短路误判）──
_ensure_service() {
  local svc="$1"
  if _service_healthy "$svc"; then
    return 0
  fi
  _log_guard "pull_up_start" "$svc" "检测到不健康，调用 restart_system.sh restart（stop+start 幂等）"
  if "$RESTART_SCRIPT" "$svc" restart >> "$GUARD_LOG" 2>&1; then
    _log_guard "pull_up_ok" "$svc" "restart_system.sh restart 完成"
    return 0
  else
    _log_guard "pull_up_fail" "$svc" "restart_system.sh restart 失败（进入退避）"
    return 1
  fi
}

# ── 指数退避（成功即清零；连续失败递增）──
_backoff_sleep() {
  local fail_count="$1"
  local delay
  if (( fail_count <= 0 )); then
    delay=0
  else
    delay=$(( GUARD_BACKOFF_BASE_S * (2 ** (fail_count - 1)) ))
    (( delay > GUARD_MAX_BACKOFF_S )) && delay="$GUARD_MAX_BACKOFF_S"
  fi
  if (( delay > 0 )); then
    _log_guard "backoff" "" "连续失败 ${fail_count} 次，退避 ${delay}s（防重启风暴）"
    sleep "$delay"
  fi
}

# ── 单次检测 + 拉起 ──
_guard_once() {
  local svc fail_count=0
  for svc in web feishu; do
    if ! _service_healthy "$svc"; then
      _log_guard "detect_fail" "$svc" "服务不健康"
      if _ensure_service "$svc"; then
        _log_guard "recovered" "$svc" "服务已恢复"
        fail_count=0
      else
        fail_count=$(( fail_count + 1 ))
      fi
    fi
  done
  return "$(( fail_count > 0 ? 1 : 0 ))"
}

# ── 守护循环 ──
_guard_loop() {
  _log_guard "guard_start" "" "守护循环启动（周期 ${GUARD_POLL_S}s，退避上限 ${GUARD_MAX_BACKOFF_S}s）"
  local fail_count=0
  while true; do
    if _guard_once; then
      fail_count=0
    else
      fail_count=$(( fail_count + 1 ))
      _backoff_sleep "$fail_count"
    fi
    sleep "$GUARD_POLL_S"
  done
}

# ── 守护自身状态 ──
_guard_status() {
  echo "[guard_system] 守护自身 PID: $$"
  echo "[guard_system] 锁目录: $_LOCK_DIR"
  if [[ -f "$GUARD_LOG" ]]; then
    echo "[guard_system] guard.log 尾部:"
    tail -5 "$GUARD_LOG"
  else
    echo "[guard_system] guard.log 尚未生成"
  fi
}

# ── 主入口 ──
case "${1:-loop}" in
  once)   _guard_once ;;
  status) _guard_status ;;
  loop|*) _guard_loop ;;
esac