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

# ── 工作区变更检测（2026-08-16：.env/providers.json/src/skills 变化 → 提醒重启）──
# 原则（RULE-AI-00 程序最小化）：只"检测 + 记录 + 写 flag"，不自动重启——
# 变更生效需人工/AI 确认后手动 restart_system.sh restart（restart 末尾自动 ack 清 flag）。
# 指纹 = 监视文件内容哈希聚合（变化即指纹变）；基线存 data/guard_workspace.baseline。
# 监视范围（变化需重启才生效的）: .env / data/providers.json / src/**/*.py / skills/**/SKILL.md
GUARD_WS_BASELINE="${GUARD_WS_BASELINE:-$DATA_DIR/guard_workspace.baseline}"
GUARD_WS_FLAG="${GUARD_WS_FLAG:-$DATA_DIR/workspace_changed.json}"

_workspace_fingerprint() {
  # 监视文件的内容哈希聚合（文件列表稳定排序; 内容哈希抗 mtime 抖动）
  local files
  files="$(printf '%s\n' "$PROJECT_DIR/.env" "$PROJECT_DIR/data/providers.json"; \
           find "$PROJECT_DIR/src" "$PROJECT_DIR/skills" -name '*.py' -o -name 'SKILL.md' 2>/dev/null | sort)"
  local out=""
  local f
  while IFS= read -r f; do
    [[ -f "$f" ]] && out="$out$(shasum -a 256 "$f" 2>/dev/null | cut -d' ' -f1) "
  done <<< "$files"
  printf '%s' "$out" | shasum -a 256 | cut -d' ' -f1
}

_check_workspace_change() {
  local fp="$(_workspace_fingerprint)"
  if [[ ! -f "$GUARD_WS_BASELINE" ]]; then
    printf '%s\n' "$fp" > "$GUARD_WS_BASELINE"
    _log_guard "workspace_baseline" "" "建立工作区基线（首次, 不告警）"
    return 0
  fi
  local base
  base="$(cat "$GUARD_WS_BASELINE" 2>/dev/null || true)"
  if [[ "$fp" == "$base" ]]; then
    return 0  # 无变化
  fi
  # 变化 → 写 flag（flag 已存在则刷新内容, 不重复刷日志告警等级）
  # 变更文件清单: 统一按 -nt（新于基线）检测（.env/providers.json 同样走检测, 不无条件列）
  local changed_files
  changed_files="$(for f in "$PROJECT_DIR/.env" "$PROJECT_DIR/data/providers.json"; do [[ "$f" -nt "$GUARD_WS_BASELINE" ]] && echo "${f#$PROJECT_DIR/}"; done; \
    find "$PROJECT_DIR/src" "$PROJECT_DIR/skills" \( -name '*.py' -o -name 'SKILL.md' \) -newer "$GUARD_WS_BASELINE" 2>/dev/null | head -20 | sed "s|$PROJECT_DIR/||")"
  python3 - "$GUARD_WS_FLAG" "$changed_files" <<'PYEOF' 2>/dev/null || true
import json, sys
from datetime import datetime, UTC
flag, changed = sys.argv[1], [x for x in sys.argv[2].splitlines() if x]
json.dump({
    "changed_at": datetime.now(UTC).isoformat(),
    "changed_files": changed,
    "note": "工作区代码/配置已变更，运行中进程仍是旧状态",
    "action": "bash scripts/restart_system.sh restart  # 确认后重启生效",
}, open(flag, "w"), ensure_ascii=False, indent=2)
PYEOF
  _log_guard "workspace_changed" "" "检测到工作区变更（需重启生效）: $(echo "$changed_files" | tr '\n' ' ' | cut -c1-120)"
}

# 手动 ack（restart 末尾调用/人工确认后调用）：清 flag + 刷新基线
_ack_workspace() {
  rm -f "$GUARD_WS_FLAG"
  _workspace_fingerprint > "$GUARD_WS_BASELINE"
  _log_guard "workspace_ack" "" "变更已确认处理, flag 清除 + 基线刷新"
}

# ── 主入口 ──
# 无需锁的子命令（不与守护循环冲突）先行处理：status / workspace-check / ack-workspace
case "${1:-loop}" in
  status) _guard_status; exit 0 ;;
  workspace-check) _check_workspace_change; exit 0 ;;
  ack-workspace) _ack_workspace; exit 0 ;;
esac

# ── 防多实例（mkdir 原子锁：POSIX 兼容，macOS 无 flock 命令）──
# 持有锁目录即单实例；拿到锁的实例退出前释放（trap）。launchd 反复拉起时仅一个存活。
# 注：仅 once/loop 需要锁（workspace-check/ack-workspace/status 在上方已先行处理）
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
  # P0: 维护标记（restart_system.sh 重启期间）→ 跳过本轮，避免与重启竞态抢跑
  if [[ -f "$DATA_DIR/maintenance.lock" ]]; then
    _log_guard "skip_maintenance" "" "检测到维护标记，跳过本轮（restart 进行中）"
    return 0
  fi
  # 2026-08-16: 工作区变更检测（健康检查之后; 仅提醒不自动重启）
  _check_workspace_change
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

# ── 主入口（需锁的分支：once/loop；status/workspace-check/ack-workspace 在上方先行处理）──
case "${1:-loop}" in
  once)   _guard_once ;;
  loop|*) _guard_loop ;;
esac