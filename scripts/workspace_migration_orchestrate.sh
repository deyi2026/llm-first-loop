#!/bin/bash
# P1-3 迁移编排（恢复路径修复版，2026-10-25 R2）
# 事故复盘（orchestration-20261025-163049.jsonl）：migrate ok → env_append ok →
#   start "ok"（实为 restart worker 受理即记成功）→ 300s health fail → 编排直接
#   退出：无 rollback、verify 未执行、maintenance.lock 残留至人工清理。
#   根因之一 .env 被 auth.py rehash 写回 bug 污染（WEB_SESSION_TTL_SECONDS 拼入
#   哈希行）→ 起服重读 .env 登录配置无效。auth.py 已修复（16a90f7a0）；本脚本
#   修复编排自身的恢复路径缺口（六项，用户审查确认）：
#   1) 停机前配置预检：scripts/workspace_env_precheck.py 对生产 .env 做结构校验
#      （哈希行独立完整 + 独立重读解析模拟重启重读），坏配置中止于停服前。
#   2) worker 终态跟踪：restart 受理后轮询 service-control-actions/<id>.json
#      真实终态（succeeded/failed）+ manifest pid/端口就绪，不再把受理记 start ok。
#   3) 四类失败分支：migrate 失败→数据回滚+旧布局起服；起服失败→优先恢复服务
#      （迁移已完成时保留新布局数据、重试一次起服；数据回滚仅当迁移未完成）；
#      health 失败→诊断包+人工指引+释放锁+非零退出；verify 失败→差异清单+
#      人工指引+释放锁。
#   4) trap EXIT/INT/TERM 全路径释放 maintenance.lock（含 health fail 退出路径）。
#   5) 停止进程收紧：manifest pid 优先；lsof 限 -sTCP:LISTEN；每 PID 停前记录
#      身份（ps comm/ppid），额外 PID 记入审计 jsonl。
#   6) 每步动作写入 orchestration-*.jsonl（失败分支详情一并落账）。
# 序列：延迟→lock→env 预检（停服前！）→停三服务→migrate→.env 追加→起服
#   （service_control restart + 终态跟踪）→health→verify→释放锁→终回执。
# 存活：以 nohup setsid 启动，宿主 web 进程被停后本脚本继续（步骤均不依赖 web）。
# 演练隔离：全部路径/端口/命令钩子可经 LFL_ORCH_* 环境变量重定向到 /tmp 镜像
#   （见 scripts/workspace_migration_drill_failures.sh），不影响生产缺省语义。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # 动态解析仓库根（脚本位于 scripts/）
DATA_DIR="${LFL_ORCH_DATA_DIR:-$REPO/data}"
AUDIT_DIR="${LFL_ORCH_AUDIT_DIR:-$DATA_DIR/audit/workspace_migration}"
ENV_FILE="${LFL_ORCH_ENV_FILE:-$REPO/.env}"
LOCK="${LFL_ORCH_LOCK:-$DATA_DIR/maintenance.lock}"
NEW_ROOT="${LFL_ORCH_NEW_ROOT:-$HOME/lfl-workspace}"
WEB_PORT="${LFL_ORCH_WEB_PORT:-8903}"
VENV_PY="$REPO/.venv/bin/python"
HELPERS="$REPO/scripts/workspace_orch_helpers.py"
ENV_PRECHECK="$REPO/scripts/workspace_env_precheck.py"
START_DELAY_S="${LFL_ORCH_START_DELAY_S:-8}"
START_TIMEOUT_S="${LFL_ORCH_START_TIMEOUT_S:-420}"    # restart worker 真实终态轮询预算
HEALTH_TIMEOUT_S="${LFL_ORCH_HEALTH_TIMEOUT_S:-300}"
SVCCTL_STUB="${LFL_ORCH_SVCCTL_STUB:-}"               # 演练专用 stub（service_control CLI 同语义）
REQUESTER="${LFL_ORCH_REQUESTER:-p1-3-orchestrate}"
export LFL_DEFAULT_WORKSPACE_ROOT="$NEW_ROOT"

TS="$(date +%Y%m%d-%H%M%S)"
JSONL="$AUDIT_DIR/orchestration-$TS.jsonl"
LOGF="$AUDIT_DIR/orchestration-$TS.log"
MIG_AUDIT="$AUDIT_DIR/migration-$TS.json"
ACTIONS_DIR="$DATA_DIR/runtime/service-control-actions"

mkdir -p "$AUDIT_DIR" "$ACTIONS_DIR"
exec >>"$LOGF" 2>&1

# ── 修复4：全路径锁释放——EXIT/INT/TERM 都经 on_exit→release_lock ──
LOCK_HELD=0
LOCK_RELEASED=0
MIGRATE_OK=0
START_ACTION_ID=""

esc() { # JSON 字符串转义（detail 层；控制字符压平，截断 800 字符防刷屏）
  local s="${1:-}"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  s="${s//$'\n'/ }"; s="${s//$'\r'/}"; s="${s//$'\t'/ }"
  printf '%s' "${s:0:800}"
}

emit() { # emit <step> <status> [detail] → jsonl（语义保持）+ log
  local step="$1" status="$2" detail="${3:-}" d=""
  [[ -n "$detail" ]] && d=",\"detail\":\"$(esc "$detail")\""
  printf '{"ts":"%s","step":"%s","status":"%s"%s}\n' \
    "$(date -Iseconds)" "$step" "$status" "$d" >>"$JSONL"
  printf '[%s] %s %s %s\n' "$(date +%T)" "$step" "$status" "$detail"
}

release_lock() { # 幂等；trap 与显式路径共用
  [[ "$LOCK_HELD" == "1" && "$LOCK_RELEASED" == "0" ]] || return 0
  if rm -f "$LOCK" 2>/dev/null; then
    LOCK_RELEASED=1
    emit lock released "${1:-释放锁}（$LOCK）"
  else
    emit lock warn "释放失败: $LOCK（人工清理）"
  fi
}

on_exit() {
  local rc=$?
  trap - EXIT INT TERM
  # 所有退出路径（含 health fail/verify fail/SIGTERM/未捕获错误）最终经此处；
  # 锁残留即事故复发，必须兜底释放。
  release_lock "EXIT trap 兜底（rc=$rc）"
  emit orchestrate exit "rc=$rc"
}
on_signal() {
  emit orchestrate signal "收到 SIG$1：经 trap 释放锁后退出（143）"
  trap - INT TERM
  exit 143
}
trap on_exit EXIT
trap 'on_signal TERM' TERM
trap 'on_signal INT' INT

alive() { kill -0 "$1" 2>/dev/null; }

json_field() { # json_field <file> <field>（辅助脚本独立读，无 jq 依赖）
  [[ -f "$1" ]] || return 0
  "$VENV_PY" "$HELPERS" json-field "$1" "$2" 2>/dev/null
}

svcctl() { # service_control 统一入口（演练 stub 同语义替换）
  if [[ -n "$SVCCTL_STUB" ]]; then
    bash "$SVCCTL_STUB" "$@"
  else
    (cd "$REPO" && "$VENV_PY" -m llm_loop.runtime.service_control "$@")
  fi
}

manifest_pid() { json_field "$DATA_DIR/runtime/runtime_manifest.$1.json" pid; }

web_port_ready() { curl -fsS -m 5 "http://127.0.0.1:$WEB_PORT/auth/status" >/dev/null 2>&1; }

service_up() { # manifest pid 存活 或 端口就绪（任一）
  local p; p="$(manifest_pid web)"
  { [[ -n "$p" && "$p" =~ ^[0-9]+$ ]] && alive "$p"; } || web_port_ready
}

migrate_cmd() { # migrate_cmd <migrate|rollback|verify> [extra]
  (cd "$REPO" && "$VENV_PY" scripts/migrate_workspace.py "$1" \
    --data-dir "$DATA_DIR" --new-root "$NEW_ROOT" --web-port "$WEB_PORT" \
    --audit-file "$MIG_AUDIT" ${2:-})
}

# ── 修复5：停止进程收紧 ──
stop_one() { # stop_one <name> <manifest_pid> [port]
  local name="$1" pid="${2:-}" port="${3:-}" p all="" extra="" identities="" idline
  # lsof 限定 LISTEN（原不限状态会把仅持连接的无关进程一并误杀）
  if [[ -n "$port" ]]; then
    extra="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NF{print}' | tr '\n' ' ')"
  fi
  for p in $pid $extra; do
    [[ "$p" =~ ^[0-9]+$ && "$p" != "$$" ]] || continue
    [[ " $all " == *" $p "* ]] || all+="$p "
  done
  if [[ -z "$all" ]]; then
    emit "stop_$name" "skip" "无存活目标 pid（manifest=${pid:-无}; lsof LISTEN=${extra:-无}）"
    return 0
  fi
  # 停前记录每 PID 身份（pid/ppid/comm；不记参数防泄密）——含额外 PID 一并入审计 jsonl
  for p in $all; do
    idline="$(ps -p "$p" -o pid=,ppid=,comm= 2>/dev/null | awk '{printf "pid=%s ppid=%s comm=%s; ", $1, $2, $3}')"
    identities+="${idline:-pid=$p（ps 无回执，身份未知）; }"
  done
  emit "stop_$name" "targets" "停前清单 manifest=${pid:-无} lsof_LISTEN=${extra:-无} → ${identities%; }"
  local survivors="" i
  for p in $all; do kill -TERM "$p" 2>/dev/null || true; done
  for i in $(seq 1 30); do
    survivors=""
    for p in $all; do alive "$p" && survivors+="$p "; done
    [[ -z "$survivors" ]] && break
    sleep 0.5
  done
  if [[ -n "${survivors:-}" ]]; then
    for p in $survivors; do kill -KILL "$p" 2>/dev/null || true; done
    for i in $(seq 1 30); do
      survivors=""
      for p in $all; do alive "$p" && survivors+="$p "; done
      [[ -z "$survivors" ]] && break
      sleep 0.1
    done
  fi
  if [[ -n "${survivors:-}" ]]; then
    emit "stop_$name" "fail" "KILL 后仍存活: $survivors"
    return 1
  fi
  emit "stop_$name" "ok" "已停: $all"
  return 0
}

# ── 修复1：停机前 .env 配置预检 ──
env_precheck() {
  local out
  # --strict-missing-hash（precheck 自身契约：生产启用登录时使用）——非 strict 下
  # WEB_LOGIN_PASSWORD_HASH 整体缺失仅提示不阻断，会在停服→迁移→健康检查链上
  # 复发断服窗口（本编排器面向的生产恰启用密码登录）。
  if ! out="$("$VENV_PY" "$ENV_PRECHECK" --strict-missing-hash "$ENV_FILE" 2>&1)"; then
    emit env_precheck fail "停服前 .env 结构校验未通过（中止于停服前，服务未动）: $(printf '%s' "$out" | head -c 700)"
    return 1
  fi
  emit env_precheck ok ".env 结构校验通过（哈希行独立完整 + 独立重读解析；不打印值）: $ENV_FILE"
  return 0
}

# ── 修复2：worker 真实终态跟踪 ──
action_status() { json_field "$ACTIONS_DIR/$1.json" status; }

wait_worker_terminal() { # wait_worker_terminal <action_id> <timeout_s> <progress_step>
  local aid="$1" deadline=$(( $(date +%s) + $2 )) step="$3" st="" last=0 now
  while (( $(date +%s) < deadline )); do
    st="$(action_status "$aid")"
    case "$st" in
      succeeded|failed) printf '%s' "$st"; return 0 ;;
    esac
    now="$(date +%s)"
    if (( now - last >= 60 )); then
      last="$now"
      # >&2：本函数被 start_services 以 $( ) 捕获返回值，pending 进度行走 stdout
      # 会污染 $st（如 "pending 行\nsucceeded" → 判非 succeeded → recover_start
      # 二次重启）。emit 全局行为不变（jsonl 照写、log 行改道 stderr→LOGF）。
      emit "$step" pending "worker 状态=${st:-未知}，继续等待真实终态（action_id=$aid）" >&2
    fi
    sleep 3
  done
  printf '%s' "${st:-timeout}"
  return 1
}

start_services() { # start_services <requester> <timeout_s> —— rc0=服务确认活
  local requester="$1" tmo="$2" out rc st aid_detail
  START_ACTION_ID=""
  out="$(svcctl restart --data-dir "$DATA_DIR" --target all --requester "$requester" 2>&1)"
  rc=$?
  if [[ $rc -ne 0 ]]; then
    printf '%s\n' "$out" >"$AUDIT_DIR/start-dispatch-fail-$TS.txt"
    emit start fail "service_control restart 受理失败 rc=$rc（回执: $AUDIT_DIR/start-dispatch-fail-$TS.txt）"
    return 1
  fi
  START_ACTION_ID="$(printf '%s\n' "$out" | grep -o '"action_id"[: ]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
  if [[ -z "$START_ACTION_ID" ]]; then
    printf '%s\n' "$out" >"$AUDIT_DIR/start-dispatch-fail-$TS.txt"
    emit start fail "restart 回执缺少 action_id（无法跟踪终态；回执: $AUDIT_DIR/start-dispatch-fail-$TS.txt）"
    return 1
  fi
  emit start accepted "restart worker 已受理 action_id=$START_ACTION_ID（受理≠成功，轮询真实终态）"
  if st="$(wait_worker_terminal "$START_ACTION_ID" "$tmo" start)"; then
    if [[ "$st" == "succeeded" ]]; then
      if service_up; then
        emit start ok "worker 终态=succeeded 且服务进程存活（action_id=$START_ACTION_ID）"
        return 0
      fi
      emit start fail "worker 报 succeeded 但 web 进程未活且端口未就绪（action_id=$START_ACTION_ID）"
      return 1
    fi
    aid_detail="$(json_field "$ACTIONS_DIR/$START_ACTION_ID.json" detail)"
    emit start fail "worker 终态=failed（action_id=$START_ACTION_ID）detail=${aid_detail:-无}"
    return 1
  fi
  # 超时未见终态：服务已活则放行（终态记录欠账如实 warn），未活判起服失败
  if service_up; then
    emit start warn "等待终态超时（${tmo}s，最后状态=${st:-未知}）但服务已活；继续 health 校验"
    return 0
  fi
  emit start fail "等待终态超时（${tmo}s，最后状态=${st:-未知}）且服务未活（action_id=$START_ACTION_ID）"
  return 1
}

collect_diag_bundle() { # collect_diag_bundle <tag> —— 健康诊断包；回显路径
  local f="$AUDIT_DIR/diag-$1-$TS.txt" aid="${START_ACTION_ID:-}"
  {
    echo "== 编排诊断包 $1（$(date -Iseconds)）=="
    echo "-- web.log 尾部（$DATA_DIR/web.log）--"
    tail -n 80 "$DATA_DIR/web.log" 2>/dev/null || echo "(缺失)"
    echo "-- runtime_manifest.web.json --"
    head -c 4000 "$DATA_DIR/runtime/runtime_manifest.web.json" 2>/dev/null || echo "(缺失)"
    echo; echo "-- restart action（$aid）--"
    head -c 4000 "$ACTIONS_DIR/$aid.json" 2>/dev/null || echo "(缺失)"
    echo; echo "-- service_control show --"
    svcctl show --data-dir "$DATA_DIR" 2>&1 | head -c 4000
    echo; echo "-- 端口 $WEB_PORT LISTEN --"
    lsof -ti tcp:"$WEB_PORT" -sTCP:LISTEN 2>/dev/null || echo "(无 LISTEN)"
  } >"$f" 2>&1
  printf '%s' "$f"
}

health_wait() { # health_wait <timeout_s>
  local deadline=$(( $(date +%s) + $1 )) last=0 now
  while (( $(date +%s) < deadline )); do
    web_port_ready && return 0
    now="$(date +%s)"
    if (( now - last >= 60 )); then last="$now"; emit health pending "端口未就绪，继续等待（deadline=$deadline）"; fi
    sleep 3
  done
  return 1
}

emit orchestrate started "编排启动 pid=$$ ts=$TS（恢复路径修复版）data=$DATA_DIR env=$ENV_FILE port=$WEB_PORT"

# 0) 起步延迟：让发射方先收到 execute_command 启动回执
if (( START_DELAY_S > 0 )); then
  sleep "$START_DELAY_S"
  emit delay ok "${START_DELAY_S}s 起步延迟完成"
else
  emit delay skip "演练模式跳过延迟"
fi

# 1) maintenance.lock（防 guard 抢跑；任何退出路径由 trap 兜底释放）
if ! touch "$LOCK"; then emit lock fail "无法创建 $LOCK"; exit 1; fi
LOCK_HELD=1
emit lock acquired "$LOCK"

# 1.5) 修复1：停机前 .env 结构预检——坏配置中止于停服前（服务未动）
if ! env_precheck; then
  emit orchestrate fail "env 预检失败：中止于停服前（服务未停、未迁移）；修复 $ENV_FILE 后重跑编排"
  release_lock "env_precheck fail（停服前中止）"
  exit 2
fi

# 2) 停三服务（web 含端口 LISTEN 收紧；本会话宿主=web，此步后发射方会话终结）
web_pid="$(manifest_pid web)"
if ! stop_one web "${web_pid:-}" "$WEB_PORT"; then
  emit orchestrate fail "web 停止失败；释放锁（guard 可拉起恢复），人工介入 $LOGF"
  exit 1
fi
feishu_pid="$(manifest_pid feishu)"
if ! stop_one feishu "${feishu_pid:-}"; then
  emit orchestrate fail "feishu 停止失败；释放锁，人工介入"
  exit 1
fi
learning_pid="$(manifest_pid learning)"
if ! stop_one learning "${learning_pid:-}"; then
  emit orchestrate fail "learning 停止失败；释放锁，人工介入"
  exit 1
fi
sleep 3
emit services_stopped ok

# 3) 迁移（失败分支一：数据回滚 + 旧布局起服恢复）
if ! migrate_cmd migrate --yes; then
  emit migrate fail "迁移失败；回滚数据布局后用旧布局起服恢复"
  if ! migrate_cmd rollback --yes; then
    emit recover_rollback warn "rollback 非零退出（分区可能半迁移；继续尝试起服）"
  fi
  if start_services "$REQUESTER-rollback" "$START_TIMEOUT_S"; then
    emit recover_rollback_start ok "已回滚并以旧布局恢复起服；迁移失败待人工检查（migrate 审计: $MIG_AUDIT）"
    release_lock "migrate 失败已回滚恢复（guard 恢复监视）"
    emit orchestrate fail "迁移失败已回滚恢复；请人工检查 $LOGF"
    exit 1
  fi
  db="$(collect_diag_bundle migratefail)"
  emit recover_rollback_start fail "回滚后起服仍失败；诊断包: $db；人工: service_control restart 或 bash scripts/restart_mirror.sh all"
  release_lock "migrate 失败且恢复失败（guard 自愈兜底）"
  exit 1
fi
MIGRATE_OK=1
emit migrate ok

# 4) .env 追加变量（幂等；行首带换行防与既有行拼接——07:52 事故形态防线）
if ! grep -q '^LFL_DEFAULT_WORKSPACE_ROOT=' "$ENV_FILE" 2>/dev/null; then
  printf '\n# P1-3(2026-10-25): 默认工作区根（服务 env 由 restart 脚本注入同值）\nLFL_DEFAULT_WORKSPACE_ROOT=%s\n' "$NEW_ROOT" >>"$ENV_FILE" \
    && emit env_append ok "$NEW_ROOT" || emit env_append warn "追加失败（不阻断：服务链不依赖 .env）"
else
  emit env_append skip "已存在"
fi

# 5) 起服（失败分支二：优先恢复服务；数据回滚仅当迁移未完成）
if ! start_services "$REQUESTER" "$START_TIMEOUT_S"; then
  if [[ "$MIGRATE_OK" == "1" ]]; then
    emit recover_start started "迁移已完成：数据保留新布局（不回滚数据）；优先恢复服务——重试一次起服"
    if start_services "$REQUESTER-recover" "$START_TIMEOUT_S"; then
      emit recover_start ok "恢复起服成功（新布局）；继续 health/verify"
    else
      db="$(collect_diag_bundle startfail)"
      emit recover_start fail "恢复起服仍失败；诊断包: $db；人工指引: (1) 检查 $ENV_FILE 结构 (2) tail $DATA_DIR/web.log (3) service_control show --data-dir $DATA_DIR；数据已迁移未回滚（migrate ok），人工核对后可重跑编排（幂等）"
      release_lock "起服失败且恢复失败（guard 自愈兜底）"
      exit 1
    fi
  else
    # 审核P2-4: 此分支当前不可达（migrate 失败已在 L320-335 exit），保留为
    # 纵深防御——若未来 migrate 路径变化（软失败），此分支保证数据回滚兜底。
    emit recover_rollback started "迁移未完成：回滚数据布局后起服恢复"
    if ! migrate_cmd rollback --yes; then
      emit recover_rollback warn "rollback 非零退出（继续尝试起服）"
    fi
    if start_services "$REQUESTER-rollback" "$START_TIMEOUT_S"; then
      emit recover_rollback_start ok "已回滚并以旧布局恢复起服"
    else
      db="$(collect_diag_bundle startfail)"
      emit recover_rollback_start fail "回滚后起服仍失败；诊断包: $db；人工: bash scripts/restart_mirror.sh all"
      release_lock "起服失败且回滚恢复失败"
      exit 1
    fi
    release_lock "起服失败已回滚恢复"
    exit 1
  fi
fi

# 6) health 等待（失败分支三：诊断包 + 人工指引 + 释放锁 + 非零退出，不静默）
if ! health_wait "$HEALTH_TIMEOUT_S"; then
  db="$(collect_diag_bundle healthfail)"
  emit health fail "${HEALTH_TIMEOUT_S}s 内 /auth/status 未就绪；诊断包: $db；人工指引: (1) tail -80 $DATA_DIR/web.log (2) cat $DATA_DIR/runtime/runtime_manifest.web.json (3) service_control show --data-dir $DATA_DIR；释放锁（guard 自愈监视），编排非零退出"
  release_lock "health fail（诊断包已产出，guard 恢复监视）"
  emit orchestrate fail "health 检查失败（详见诊断包 $db）；数据已迁移未回滚，人工处理后可重跑 verify"
  exit 1
fi
emit health ok "/auth/status 就绪"

# 7) verify（失败分支四：差异清单 + 人工指引 + 释放锁，不静默）
VOUT="$AUDIT_DIR/verify-out-$TS.json"
if ! migrate_cmd verify | tee "$VOUT"; then
  DIFFS="$("$VENV_PY" "$HELPERS" verify-diffs "$VOUT" 2>/dev/null)"
  emit verify fail "verify 未全绿；差异项: ${DIFFS:-未知}；完整输出: $VOUT；人工指引: 核对差异项后可重跑 migrate_workspace.py verify；数据已迁移（migrate ok）不自动回滚；释放锁退出"
  release_lock "verify fail（差异清单已产出）"
  emit orchestrate fail "verify 未全绿（差异: ${DIFFS:-未知}）；人工核对 $VOUT"
  exit 1
fi
emit verify ok

# 8) 收尾：释放锁、终回执
release_lock "正常完成释放锁"
emit orchestrate done "P1-3 实迁编排全部完成；新默认工作区根=$NEW_ROOT"
exit 0
