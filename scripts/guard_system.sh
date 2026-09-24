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
  # 日志去抖（2026-08-16）：agent 长任务持续编辑文件时 guard 每轮都报 → 噪音。
  # 同一"未确认变更"5 分钟内仅记一次日志（flag 每次刷新保持 architecture_status 可见）。
  GUARD_WS_LAST_LOG="${GUARD_WS_LAST_LOG:-$DATA_DIR/guard_ws_last_log.ts}"
  local now last_log
  now="$(date +%s)"
  if [[ -f "$GUARD_WS_LAST_LOG" ]]; then
    last_log="$(cat "$GUARD_WS_LAST_LOG" 2>/dev/null || echo 0)"
    if (( now - last_log < 300 )); then
      return 0  # 5 分钟去抖（flag 已写，仅抑制日志刷屏）
    fi
  fi
  printf '%s\n' "$now" > "$GUARD_WS_LAST_LOG"
  _log_guard "workspace_changed" "" "检测到工作区变更（需重启生效）: $(echo "$changed_files" | tr '\n' ' ' | cut -c1-120)"
}

# 手动 ack（restart 末尾调用/人工确认后调用）：清 flag + 刷新基线
_ack_workspace() {
  rm -f "$GUARD_WS_FLAG"
  _workspace_fingerprint > "$GUARD_WS_BASELINE"
  _log_guard "workspace_ack" "" "变更已确认处理, flag 清除 + 基线刷新"
}

# ── 守护自身状态（2026-09-24 提前定义: 原位于脚本尾部，主入口 case 分发时
# 符号未定义 → `guard_system.sh status` 恒 command not found）──
_guard_status() {
  echo "[guard_system] 守护自身 PID: $$"
  echo "[guard_system] 锁目录: ${_LOCK_DIR:-（未创建——status 无锁设计）}"
  if [[ -f "$GUARD_LOG" ]]; then
    echo "[guard_system] guard.log 尾部:"
    tail -5 "$GUARD_LOG"
  else
    echo "[guard_system] guard.log 尚未生成"
  fi
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
#
# 2026-09-24（web 死亡无人知复盘）: 对齐 service_control 新部署面。旧面只见
# web.pid + `llm_loop.web` 进程模式 + 固定 8902；新面 desired-state 起的是
# `llm_loop.runtime.launch <svc>` 进程，web 端口可能被占挤到 8903+——旧判定
# 对新面进程永远误报不健康（实例: pid 14036@8903 服务正常仍被判 detect_fail）。
# guard 职责收敛: 只兜进程级死亡 + 端口级失听 + 拉起兜底；半僵/部署一致性
# 归 service_control 面（verify_acknowledge），不在此越权判定。
_runtime_process_alive() {
  local svc="$1"
  # ps+grep 精确锚定（BSD pgrep -f 的 $ 锚实测不可靠: 宽匹配命中、带锚全不命中）
  # 新面: runtime.launch 模式；旧面: llm_loop.<svc> 模式。均锚定行尾防前缀误匹配。
  ps -eo command= 2>/dev/null | grep -E -- "-m llm_loop[.]runtime[.]launch ${svc}$" | grep -qv grep && return 0
  ps -eo command= 2>/dev/null | grep -E -- "-m llm_loop[.]${svc}$" | grep -qv grep && return 0
  return 1
}
_service_healthy() {
  local svc="$1"
  if _runtime_process_alive "$svc"; then
    if [[ "$svc" == "web" ]]; then
      # web 进程在还需有端口在听（防"活着但没监听"卡死形态）；
      # /health 需鉴权，以 401 响应（服务应答）即视为端口健康。
      # 2026-09-24 修正：端口清单从镜像 .env 权威 WEB_PORT 起扫（默认 8903），
      # 绝不含 8902——那是主区端口；旧清单含 8902 时主区活着即可让镜像
      # web 死透仍判"健康"（跨区误判，与 plist WorkingDirectory 错指同类）。
      local port rc _wp
      _wp="$(grep -E '^WEB_PORT=' "$PROJECT_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"' || true)"
      _wp="${_wp:-8903}"
      for port in "$_wp" $((_wp + 1)) $((_wp + 2)); do
        rc="$(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:${port}/health" 2>/dev/null || true)"
        if [[ "$rc" == "200" || "$rc" == "401" ]]; then
          return 0
        fi
      done
      return 1
    fi
    # feishu/learning: 进程存活即健康底线（心跳半僵归 service_control 面）
    return 0
  fi
  local out
  out="$("$RESTART_SCRIPT" "$svc" status 2>&1 || true)"
  case "$out" in
    *"（健康）"*) return 0 ;;
    *) return 1 ;;
  esac
}

# ── 拉起服务（不健康时强制 restart：stop + start 幂等，避免"已在运行"短路误判）──
# 2026-09-24 13:08 实证：权威通道（service_control→restart_mirror.sh）停旧进程的
# 端口空窗恰被 guard 巡检命中 → detect_fail → 双通道并发重启 → 双 web 抢端口
# 一活一死，死进程写的 manifest 污染观察面（面板误报 live_pid_not_running）。
# 互斥锁：restart 脚本执行段持有 data/runtime/restart-in-progress.lock；
# 锁新鲜（<120s）时 guard 跳过本轮 pull_up（下轮巡检自然复核），不与权威通道抢。
_RESTART_LOCK="$PROJECT_DIR/data/runtime/restart-in-progress.lock"
_restart_lock_fresh() {
  [[ -f "$_RESTART_LOCK" ]] || return 1
  local age
  age=$(( $(date +%s) - $(stat -f %m "$_RESTART_LOCK" 2>/dev/null || echo 0) ))
  (( age < 120 ))
}
_ensure_service() {
  local svc="$1"
  if _service_healthy "$svc"; then
    return 0
  fi
  if _restart_lock_fresh; then
    _log_guard "skip_pull_up" "$svc" "restart 互斥锁新鲜（权威通道执行中），本轮跳过"
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

# ── 主动告知（2026-09-24 web 死亡无人知复盘）──
# 异常不能只写 guard.log 等人来查——detect_fail/pull_up_fail 即推 macOS 本地
# 通知（用户不在终端/面板前也即时可见）。GUARD_NOTIFY=0 可关。
GUARD_NOTIFY="${GUARD_NOTIFY:-1}"
_notify_guard() {
  # _notify_guard <title> <body>
  [[ "$GUARD_NOTIFY" == "1" ]] || return 0
  osascript -e "display notification \"$2\" with title \"$1\"" >/dev/null 2>&1 || true
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
      _notify_guard "LFL guard: $svc 不健康" "检测到 $svc 异常，guard 自动拉起中（data/guard.log）"
      if _ensure_service "$svc"; then
        _log_guard "recovered" "$svc" "服务已恢复"
        _notify_guard "LFL guard: $svc 已恢复" "$svc 拉起成功（guard 自动处理）"
        fail_count=0
      else
        fail_count=$(( fail_count + 1 ))
        _notify_guard "LFL guard: $svc 拉起失败" "$svc restart 失败需人工介入（guard.log / service_control status）"
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

# ── 主入口（需锁的分支：once/loop；status/workspace-check/ack-workspace 在上方先行处理）──
case "${1:-loop}" in
  once)   _guard_once ;;
  loop|*) _guard_loop ;;
esac