#!/bin/bash
# P1-3 波3 实迁编排（一次性脚本，2026-10-25）
# 前提（发射前由统筹会话确认）：备份 backup 完成 + /tmp 镜像演练 rehearse PASS +
#   EVO 环境红 skip 已合入 + 用户已确认窗口/.env/工件桶复制。
# 序列：延迟→maintenance.lock→停三服务→migrate→sed 修正两脚本过渡锚缺省→
#   .env 追加变量→起服(restart_mirror.sh all, 新根 env)→health 等待→verify→
#   释放锁→终回执。
# 存活：以 nohup setsid 启动，宿主 web 进程被停后本脚本继续（步骤均不依赖 web）。
# 回执：data/audit/workspace_migration/orchestration-<ts>.jsonl（逐步 JSONL）+
#   同名 .log（全量 stdout/stderr）。
# 失败分支：migrate 失败→尝试一次 rollback+起服恢复旧布局；起服失败→释放锁让
#   guard 拉起自愈；两处均落 FAIL 回执与人工指引。任何 FAIL 后不再静默重试。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"  # 动态解析仓库根（本脚本位于 scripts/）
DATA_DIR="$REPO/data"
AUDIT_DIR="$DATA_DIR/audit/workspace_migration"
TS="$(date +%Y%m%d-%H%M%S)"
JSONL="$AUDIT_DIR/orchestration-$TS.jsonl"
LOGF="$AUDIT_DIR/orchestration-$TS.log"
LOCK="$DATA_DIR/maintenance.lock"
NEW_ROOT="$HOME/lfl-workspace"
WEB_PORT=8903
VENV_PY="$REPO/.venv/bin/python"
export LFL_DEFAULT_WORKSPACE_ROOT="$NEW_ROOT"

mkdir -p "$AUDIT_DIR"
exec >>"$LOGF" 2>&1

emit() { # emit <step> <status> [detail]
  printf '{"ts":"%s","step":"%s","status":"%s"%s}\n' \
    "$(date -Iseconds)" "$1" "$2" "${3:+,\"detail\":\"$3\"}" >>"$JSONL"
  printf '[%s] %s %s %s\n' "$(date +%T)" "$1" "$2" "${3:-}"
}

alive() { kill -0 "$1" 2>/dev/null; }

stop_one() { # stop_one <name> <pid> [port]
  local name="$1" pid="$2" port="${3:-}" extra="" survivors="" i p
  [[ -n "$port" ]] && extra="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  local pids; pids="$(printf '%s\n%s\n' "$pid" "$extra" | awk 'NF && !seen[$1]++ {print $1}')"
  [[ -z "$pids" ]] && { emit "stop_$name" "skip" "无存活 pid"; return 0; }
  while IFS= read -r p; do [[ -n "$p" ]] && kill -TERM "$p" 2>/dev/null || true; done <<<"$pids"
  for i in $(seq 1 30); do
    survivors=""
    while IFS= read -r p; do [[ -n "$p" ]] && alive "$p" && survivors+="$p "; done <<<"$pids"
    [[ -z "$survivors" ]] && break
    sleep 0.5
  done
  if [[ -n "${survivors:-}" ]]; then
    for p in $survivors; do kill -KILL "$p" 2>/dev/null || true; done
    for i in $(seq 1 30); do
      survivors=""
      for p in $pids; do alive "$p" && survivors+="$p "; done
      [[ -z "$survivors" ]] && break
      sleep 0.1
    done
  fi
  if [[ -n "${survivors:-}" ]]; then
    emit "stop_$name" "fail" "KILL 后仍存活: $survivors"
    return 1
  fi
  emit "stop_$name" "ok" "已停: $(echo "$pids" | tr '\n' ' ')"
}

manifest_pid() {
  "$VENV_PY" -c "
import json
try:
    d=json.load(open('$DATA_DIR/runtime/runtime_manifest.$1.json'))
    print(d.get('pid') or '')
except Exception:
    print('')
" 2>/dev/null || true
}

health_wait() {
  local deadline=$(( $(date +%s) + ${1:-90} ))
  while (( $(date +%s) < deadline )); do
    if curl -fsS "http://127.0.0.1:$WEB_PORT/auth/status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

emit orchestrate started "编排启动 pid=$$ ts=$TS"

# 0) 起步延迟：让发射方（自托管会话）先收到 execute_command 启动回执
sleep 8
emit delay ok "8s 起步延迟完成"

# 1) maintenance.lock（防 guard 抢跑；任何后续失败均不释放，除非进入恢复分支）
if ! touch "$LOCK"; then emit lock fail "无法创建 $LOCK"; exit 1; fi
emit lock acquired "$LOCK"

# 2) 停三服务（web 含端口 listener；本会话宿主=web，此步后发射方会话终结）
web_pid="$(manifest_pid web)"
if ! stop_one web "${web_pid:-}" "$WEB_PORT"; then
  emit orchestrate fail "web 停止失败；保持 maintenance.lock，人工介入"; exit 1
fi
feishu_pid="$(manifest_pid feishu)"
stop_one feishu "${feishu_pid:-}" || { emit orchestrate fail "feishu 停止失败；保持锁"; exit 1; }
learning_pid="$(manifest_pid learning)"
stop_one learning "${learning_pid:-}" || { emit orchestrate fail "learning 停止失败；保持锁"; exit 1; }
sleep 3
emit services_stopped ok

# 3) 迁移（Phase0 兜底：三服务不在/无活跃(flock) run.lock/磁盘/目标根）
if ! (cd "$REPO" && "$VENV_PY" scripts/migrate_workspace.py migrate --yes); then
  emit migrate fail "迁移失败；尝试 rollback 恢复旧布局"
  (cd "$REPO" && "$VENV_PY" scripts/migrate_workspace.py rollback --yes) || true
  if (cd "$REPO" && "$VENV_PY" -m llm_loop.runtime.service_control restart --data-dir "$DATA_DIR" --target all --requester p1-3-orchestrate-rollback); then
    emit recover_rollback_start ok "已回滚并派发 restart worker 恢复旧布局"
    rm -f "$LOCK"; emit lock released "恢复分支释放锁（guard 恢复监视）"
    emit orchestrate fail "迁移失败已回滚恢复；请人工检查 $LOGF"
    exit 1
  fi
  emit orchestrate fail "回滚后起服仍失败；保持 maintenance.lock，人工介入（可手工: bash scripts/restart_mirror.sh all）"
  exit 1
fi
emit migrate ok

# 4) .env 追加变量（幂等；当前服务链不 source .env，作文档化配置锚点）
#    R2(P0-4 修复): sed 过渡锚切换移出编排——起服改走 service_control restart
#    （desired deployment 的 factory 有 registry-current 保护，旧代码亦挂迁移后
#    新键分区）；过渡锚的最终清理作为独立提交留给收尾批，减少窗口内变量。
if ! grep -q '^LFL_DEFAULT_WORKSPACE_ROOT=' "$REPO/.env" 2>/dev/null; then
  printf '\n# P1-3(2026-10-25): 默认工作区根=AI 默认可写区（实迁落位；服务 env 由 restart 脚本注入同值）\nLFL_DEFAULT_WORKSPACE_ROOT=%s\n' "$NEW_ROOT" >>"$REPO/.env" \
    && emit env_append ok "$NEW_ROOT" || emit env_append warn "追加失败（不阻断：服务链不依赖 .env）"
else
  emit env_append skip "已存在"
fi

# 5) 起服：service_control restart（desired-state 权威通道；detached worker
#    独立于本编排存活，worker 内部完成 stop→start→健康检查）。
#    停机态无 active run（flock 全随进程释放）→ worker 应直通不等待。
if ! (cd "$REPO" && "$VENV_PY" -m llm_loop.runtime.service_control restart --data-dir "$DATA_DIR" --target all --requester p1-3-orchestrate); then
  emit start fail "service_control restart 受理失败；保持锁，人工: $VENV_PY -m llm_loop.runtime.service_control show --data-dir $DATA_DIR"
  exit 1
fi
emit start ok "restart worker 已受理（detached 自完成）"

# 6) health 等待（worker 异步：stop+start+健康检查，宽限 300s）+ verify
if ! health_wait 300; then
  emit health fail "300s 内 /auth/status 未就绪；人工检查 data/web.log 与 service_control show 回执"; exit 1
fi
emit health ok "/auth/status 就绪"
if ! (cd "$REPO" && "$VENV_PY" scripts/migrate_workspace.py verify); then
  emit verify fail "verify 未全绿；数据已迁移（migrate ok），人工核对"; exit 1
fi
emit verify ok

# 7) 收尾：释放锁、终回执
rm -f "$LOCK"; emit lock released "正常完成释放锁"
emit orchestrate done "P1-3 实迁编排全部完成；新默认工作区根=$NEW_ROOT"
