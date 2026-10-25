#!/bin/bash
# P1-3 编排故障演练（隔离 /tmp 镜像，绝不碰生产）——2026-10-25 恢复路径修复配套.
#
# 场景（对应用户审查确认的恢复路径缺口；见 workspace_migration_orchestrate.sh 头注）：
#   A 坏哈希 .env（哈希行尾缺换行、TTL 拼入——复刻 2026-10-25 07:52 事故形态）
#     → 停机前预检必须中止：无任何 stop_* 记录（服务未停）、rc=2、锁不残留。
#   B 起服失败（restart worker 立即终态 failed）
#     → 必须走"优先恢复服务"分支：migrate ok→不回滚数据→重试一次起服；恢复也
#       失败→诊断包+人工指引+释放锁+非零退出；数据布局保持新键（未回滚）。
#   B2 服务忙碌（worker 停留 waiting_for_idle 永不终态——真实链路长任务等待态）
#     → 等待终态超时且服务未活 → 同一起服失败分支（超时变体），释放锁。
#   C 健康检查失败（worker succeeded + manifest pid 活，但端口不监听）
#     → 诊断包（web.log 尾部/manifest/show/action）+ 人工指引 + 释放锁 + rc=1。
#   D 编排异常退出（SIGTERM 打在 health 等待期）
#     → trap 释放 maintenance.lock；jsonl 留 signal 与 lock released 记录；rc=143。
#
# 产出演练报告：data/audit/workspace_migration/drill-failures-<ts>.md。
# 安全边界：所有 LFL_ORCH_* 全量重定向 /tmp 镜像；service_control 走 stub（绝不
# 触发真实 restart）；演练端口 18xxx（避开生产 8903）；演练前后断言生产 .env
# sha 与 maintenance.lock 状态不变。migrate/verify 走真实脚本、仅作用于镜像数据。
# 内嵌 keys.py/gen_env.py/svcctl-stub.sh 以 base64 落盘（防生成/审查层转义失真）。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO/.venv/bin/python"
ORCH="$REPO/scripts/workspace_migration_orchestrate.sh"
DRILL_PORT="${LFL_DRILL_PORT:-18903}"
KEEP="${LFL_DRILL_KEEP:-0}"
WORK="$(mktemp -d /tmp/lfl-migration-drill-XXXXXX)"
TS="$(date +%Y%m%d-%H%M%S)"
REPORT_DIR="$REPO/data/audit/workspace_migration"
REPORT="$REPORT_DIR/drill-failures-$TS.md"
declare -a REPORT_ROWS=()
FAIL_COUNT=0

log() { printf '[drill %s] %s\n' "$(date +%T)" "$*"; }

# ── 生产护栏基线（演练前）──
PROD_ENV_SHA_BEFORE="$(shasum -a 256 "$REPO/.env" 2>/dev/null | awk '{print $1}')"
PROD_LOCK_BEFORE="absent"; [[ -f "$REPO/data/maintenance.lock" ]] && PROD_LOCK_BEFORE="present"

# ── 演练端口可用性（防误碰真实监听）──
if lsof -ti tcp:"$DRILL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "FAIL: 演练端口 $DRILL_PORT 已被占用（LFL_DRILL_PORT 换端口重试）"
  exit 3
fi
if [[ "$DRILL_PORT" == "8903" ]]; then
  log "FAIL: 拒绝使用生产端口 8903 做演练"
  exit 3
fi

decode_to() { printf '%s' "$2" | base64 -d >"$1"; chmod +x "$1"; }

KEYS_B64='aW1wb3J0IHN5cwpzeXMucGF0aC5pbnNlcnQoMCwgc3lzLmFyZ3ZbM10gKyAiL3NyYyIpCmZyb20gbGxtX2xvb3Aud29ya3NwYWNlLnN0b3JlIGltcG9ydCB3b3Jrc3BhY2Vfa2V5LCBXb3Jrc3BhY2VTdG9yZQpmcm9tIGxsbV9sb29wLndvcmtzcGFjZS5hcnRpZmFjdHMgaW1wb3J0IF93b3Jrc3BhY2VfYnVja2V0LCB3b3Jrc3BhY2Vfc2NvcGUKcmVwbywgbmV3cm9vdCwgbWlycm9yX2RhdGEgPSBzeXMuYXJndlsxXSwgc3lzLmFyZ3ZbMl0sIHN5cy5hcmd2WzNdCnByaW50KCJPTERfS0VZPSciICsgd29ya3NwYWNlX2tleShyZXBvKSArICInIikKcHJpbnQoIk5FV19LRVk9JyIgKyB3b3Jrc3BhY2Vfa2V5KG5ld3Jvb3QpICsgIiciKQpwcmludCgiT0xEX0JVQ0tFVD0nIiArIF93b3Jrc3BhY2VfYnVja2V0KHdvcmtzcGFjZV9zY29wZShyZXBvKSkgKyAiJyIpCnByaW50KCJORVdfQlVDS0VUPSciICsgX3dvcmtzcGFjZV9idWNrZXQod29ya3NwYWNlX3Njb3BlKG5ld3Jvb3QpKSArICInIikKc3RvcmUgPSBXb3Jrc3BhY2VTdG9yZShtaXJyb3JfZGF0YSkKc3RvcmUucmVnaXN0ZXJfYW5kX3N3aXRjaChyZXBvKQpwcmludCgiUkVHSVNURVJFRD0xIikK'
ENVGEN_B64='aW1wb3J0IGJhc2U2NCwgaGFzaGxpYiwgc2VjcmV0cywgc3lzCm1vZGUsIHBhdGggPSBzeXMuYXJndlsxXSwgc3lzLmFyZ3ZbMl0Kc2FsdCA9IGJhc2U2NC51cmxzYWZlX2I2NGVuY29kZShzZWNyZXRzLnRva2VuX2J5dGVzKDE2KSkuZGVjb2RlKCkucnN0cmlwKCI9IikKZGlnZXN0ID0gYmFzZTY0LnVybHNhZmVfYjY0ZW5jb2RlKAogICAgaGFzaGxpYi5wYmtkZjJfaG1hYygic2hhMjU2IiwgYiJkcmlsbC1wYXNzd29yZCIsIHNlY3JldHMudG9rZW5fYnl0ZXMoMTYpLCA2MDAwMDApCikuZGVjb2RlKCkucnN0cmlwKCI9IikKaCA9IGYicGJrZGYyX3NoYTI1NiQ2MDAwMDAke3NhbHR9JHtkaWdlc3R9IgppZiBtb2RlID09ICJnb29kIjoKICAgIGJvZHkgPSBmIiMgZHJpbGwgZW52XG5XRUJfTE9HSU5fUEFTU1dPUkRfSEFTSD17aH1cbldFQl9TRVNTSU9OX1RUTF9TRUNPTkRTPTQzMjAwXG4iCmVsc2U6CiAgICBib2R5ID0gZiIjIGRyaWxsIGVudlxuV0VCX0xPR0lOX1BBU1NXT1JEX0hBU0g9e2h9V0VCX1NFU1NJT05fVFRMX1NFQ09ORFM9NDMyMDBcbiIKb3BlbihwYXRoLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpLndyaXRlKGJvZHkpCnByaW50KCJFTlZfV1JJVFRFTj0iICsgbW9kZSkK'
STUB_B64='IyEvYmluL2Jhc2gKIyDmvJTnu4Mgc3R1Yu+8muaooeaLnyBzZXJ2aWNlX2NvbnRyb2wgcmVzdGFydC9zaG93IENMSe+8iOe7neS4jeinpuWPkeecn+WuniByZXN0YXJ077yJ44CCCiMg5qih5byP77yITEZMX0RSSUxMX01PREXvvInvvJpzdGFydC1mYWlsPXdvcmtlciDnq4vljbMgZmFpbGVk77ybYnVzeT3msLjov5wgd2FpdGluZ++8mwojIGhlYWx0aC1mYWlsPXN1Y2NlZWRlZCArIOWGmSBsaXZlIHBpZCBtYW5pZmVzdO+8iOerr+WPo+S4jeebkeWQrO+8ieOAggpzZXQgLXVvIHBpcGVmYWlsCmNtZD0iJHsxOi19Ijsgc2hpZnQgfHwgdHJ1ZQpEQVRBX0RJUj0iIjsgUkVRPSIiCndoaWxlIFtbICQjIC1ndCAwIF1dOyBkbwogIGNhc2UgIiQxIiBpbgogICAgLS1kYXRhLWRpcikgREFUQV9ESVI9IiQyIjsgc2hpZnQgMiA7OwogICAgLS1yZXF1ZXN0ZXIpIFJFUT0iJDIiOyBzaGlmdCAyIDs7CiAgICAqKSBzaGlmdCA7OwogIGVzYWMKZG9uZQpNT0RFPSIke0xGTF9EUklMTF9NT0RFOi1oZWFsdGgtZmFpbH0iCmNhc2UgIiRjbWQiIGluCiAgc2hvdykKICAgIHByaW50ZiAneyJnZW5lcmF0aW9uIjoxLCJydW50aW1lX3Jvb3QiOiJkcmlsbCIsImNvbnZlcmdlbmNlIjp7fX1cbicKICAgIDs7CiAgcmVzdGFydCkKICAgIGFpZD0ic3ZjLWRyaWxsLSQoZGF0ZSArJXMpLSRSQU5ET00iCiAgICBhZGlyPSIkREFUQV9ESVIvcnVudGltZS9zZXJ2aWNlLWNvbnRyb2wtYWN0aW9ucyIKICAgIG1rZGlyIC1wICIkYWRpciIgIiREQVRBX0RJUi9ydW50aW1lIgogICAgY2FzZSAiJE1PREUiIGluCiAgICAgIHN0YXJ0LWZhaWwpIHN0PSJmYWlsZWQiOyBkZXQ9ImRyaWxsOiByZXN0YXJ0IHdvcmtlciBmYWlsZWQgKCRSRVEpIiA7OwogICAgICBidXN5KSBzdD0id2FpdGluZ19mb3JfaWRsZSI7IGRldD0iZHJpbGw6IHRhcmdldCBidXN5LCB3b3JrZXIgd2FpdGluZyAoJFJFUSkiIDs7CiAgICAgICopCiAgICAgICAgc3Q9InN1Y2NlZWRlZCI7IGRldD0iZHJpbGw6IHdvcmtlciBzdWNjZWVkZWQgKCRSRVEpOyBtYW5pZmVzdCBsaXZlIHBpZCwgcG9ydCBub3QgbGlzdGVuaW5nIgogICAgICAgICMg5YWz6ZSu77ya5ZCO5Y+w6L+b56iL5LiJ6YeN6YeN5a6a5ZCR77yIc3RkaW4vb3V0L2Vycu+8ie+8jOWQpuWImeWRveS7pOabv+aNoueuoemBk+etieWugyBFT0Yg6ICM5oyC6LW3CiAgICAgICAgc2xlZXAgNjAwIDwvZGV2L251bGwgPi9kZXYvbnVsbCAyPiYxICYgU1BJRD0kIQogICAgICAgIHByaW50ZiAneyJzZXJ2aWNlIjoid2ViIiwicGlkIjolcywic3RhcnRlZF9hdCI6ImRyaWxsIiwiZGF0YV9kaXIiOiIlcyJ9XG4nICIkU1BJRCIgIiREQVRBX0RJUiIgXAogICAgICAgICAgPiIkREFUQV9ESVIvcnVudGltZS9ydW50aW1lX21hbmlmZXN0LndlYi5qc29uIgogICAgICAgIDs7CiAgICBlc2FjCiAgICBwcmludGYgJ3sic2NoZW1hIjoic2VydmljZS1jb250cm9sLWFjdGlvbi92MSIsImFjdGlvbl9pZCI6IiVzIiwiYWN0aW9uIjoicmVzdGFydCIsInRhcmdldCI6ImFsbCIsImRlcGxveW1lbnRfaWQiOiJkZXBsb3ktZHJpbGwiLCJkZXBsb3ltZW50X2dlbmVyYXRpb24iOjEsInJlcXVlc3Rlcl9zZXNzaW9uX2lkIjoiJXMiLCJzdGF0dXMiOiIlcyIsImNyZWF0ZWRfYXQiOiJkcmlsbCIsInVwZGF0ZWRfYXQiOiJkcmlsbCIsImRldGFpbCI6IiVzIiwid29ya2VyX3BpZCI6MH1cbicgXAogICAgICAiJGFpZCIgIiRSRVEiICIkc3QiICIkZGV0IiA+IiRhZGlyLyRhaWQuanNvbiIKICAgIHByaW50ZiAneyJvayI6dHJ1ZSwiYWN0aW9uX2lkIjoiJXMiLCJ0YXJnZXQiOiJhbGwiLCJnZW5lcmF0aW9uIjoxfVxuJyAiJGFpZCIKICAgIHByaW50ZiAneyJvayI6dHJ1ZSwiYWN0aW9uX2lkIjoiJXMiLCJzdGF0dXMiOiIlcyIsImRldGFjaGVkIjp0cnVlLCJoaW50IjoiZHJpbGwgc3R1YiByZWNlaXB0In1cbicgIiRhaWQiICIkc3QiCiAgICA7OwogICopCiAgICBwcmludGYgJ3sib2siOmZhbHNlLCJlcnJvciI6ImRyaWxsIHN0dWI6IHVuc3VwcG9ydGVkIGNtZCAlcyJ9XG4nICIkY21kIiA+JjIKICAgIGV4aXQgMiA7Owplc2FjCg=='

newest_jsonl() { ls -t "$1"/orchestration-*.jsonl 2>/dev/null | head -1; }
has_step() { grep -q "\"step\":\"$2\",\"status\":\"$3\"" "$1" 2>/dev/null; }
record() { # record <场景> <期望> <实测> <PASS|FAIL>
  REPORT_ROWS+=("| $1 | $2 | $3 | $4 |")
  if [[ "$4" != "PASS" ]]; then FAIL_COUNT=$((FAIL_COUNT+1)); log "SCEN $1 FAIL: $3"; fi
  log "SCEN $1 => $4 ($3)"
}
collect_sleep_pids() {
  local m p
  for m in "$WORK"/*/data/runtime/runtime_manifest.web.json; do
    [[ -f "$m" ]] || continue
    p="$(grep -o '"pid":[0-9]*' "$m" | head -1 | tr -dc 0-9)"
    [[ -n "$p" ]] && kill "$p" 2>/dev/null
  done
}

# ── 镜像数据布局（每场景独立）+ 演练编排执行 ──
stage_mirror() { # stage_mirror <scen_dir> <env_mode>
  local sc="$1" mode="$2"
  mkdir -p "$sc/data" "$sc/audit"
  eval "$("$VENV_PY" "$WORK/keys.py" "$REPO" "$sc/newroot" "$sc/data")"
  "$VENV_PY" "$WORK/gen_env.py" "$mode" "$sc/env"
  local part="$sc/data/sessions/$OLD_KEY/2026/10/25"
  mkdir -p "$part" "$sc/data/sessions/.identity" "$sc/data/artifacts/records/$OLD_BUCKET/2026"
  printf '{"sid":"a","turn":1}\n' >"$part/sess-a.jsonl"
  printf '{"owner":"%s","claimed_at":"drill"}\n' "$OLD_KEY" >"$sc/data/sessions/.identity/sess-a.json"
  printf '{"id":"r1","canonical_path":"/x"}\n' >"$sc/data/artifacts/records/$OLD_BUCKET/2026/r1.json"
  printf 'drill web.log line1\nauth config invalid drill\n' >"$sc/data/web.log"
}

run_orch() { # run_orch <scen_dir> <env_mode> <mode> <start_timeout> <health_timeout> [fg|bg]
  local sc="$1" mode="$2" dmode="$3" sto="$4" hto="$5" fgbg="${6:-fg}"
  stage_mirror "$sc" "$mode"
  if [[ "$fgbg" == "bg" ]]; then
    # exec：$! 直接指向编排进程本体（SIGTERM 才能直达编排 trap，
    # 否则 TERM 只打在函数子壳上、编排进程成孤儿继续跑）
    LFL_ORCH_DATA_DIR="$sc/data" \
    LFL_ORCH_AUDIT_DIR="$sc/audit" \
    LFL_ORCH_ENV_FILE="$sc/env" \
    LFL_ORCH_LOCK="$sc/data/maintenance.lock" \
    LFL_ORCH_NEW_ROOT="$sc/newroot" \
    LFL_ORCH_WEB_PORT="$DRILL_PORT" \
    LFL_ORCH_START_DELAY_S=0 \
    LFL_ORCH_START_TIMEOUT_S="$sto" \
    LFL_ORCH_HEALTH_TIMEOUT_S="$hto" \
    LFL_ORCH_SVCCTL_STUB="$WORK/svcctl-stub.sh" \
    LFL_ORCH_REQUESTER="drill-$(basename "$sc")" \
    LFL_WORKSPACE_ALLOWED_ROOTS="$REPO:$sc/newroot" \
    LFL_DRILL_MODE="$dmode" \
    exec bash "$ORCH"
  fi
  LFL_ORCH_DATA_DIR="$sc/data" \
  LFL_ORCH_AUDIT_DIR="$sc/audit" \
  LFL_ORCH_ENV_FILE="$sc/env" \
  LFL_ORCH_LOCK="$sc/data/maintenance.lock" \
  LFL_ORCH_NEW_ROOT="$sc/newroot" \
  LFL_ORCH_WEB_PORT="$DRILL_PORT" \
  LFL_ORCH_START_DELAY_S=0 \
  LFL_ORCH_START_TIMEOUT_S="$sto" \
  LFL_ORCH_HEALTH_TIMEOUT_S="$hto" \
  LFL_ORCH_SVCCTL_STUB="$WORK/svcctl-stub.sh" \
  LFL_ORCH_REQUESTER="drill-$(basename "$sc")" \
  LFL_WORKSPACE_ALLOWED_ROOTS="$REPO:$sc/newroot" \
  LFL_DRILL_MODE="$dmode" \
  bash "$ORCH"
}

# ═══ 场景 A：坏哈希 .env → 停机前预检中止（服务未停）═══
scen_A() {
  local sc="$WORK/A"; local rc=0
  run_orch "$sc" bad start-fail 20 10 >/dev/null 2>&1 || rc=$?
  local jl; jl="$(newest_jsonl "$sc/audit")"
  local notes="rc=$rc"
  if [[ $rc -eq 2 ]] && has_step "$jl" env_precheck fail \
     && ! grep -q '"step":"stop_' "$jl" 2>/dev/null \
     && [[ ! -f "$sc/data/maintenance.lock" ]]; then
    record A "rc=2 + env_precheck fail + 无 stop_* 记录 + 锁不残留" "$notes（jsonl: $(basename "${jl:-无}")）" PASS
  else
    record A "rc=2 + env_precheck fail + 无 stop_* 记录 + 锁不残留" "$notes（预检未拦或服务被停/锁残留；jsonl: ${jl:-无}）" FAIL
  fi
}

# ═══ 场景 B：起服失败 → 优先恢复服务分支（数据不回滚）═══
scen_B() {
  local sc="$WORK/B"; local rc=0
  run_orch "$sc" good start-fail 20 10 >/dev/null 2>&1 || rc=$?
  local jl; jl="$(newest_jsonl "$sc/audit")"
  local ok=1
  [[ $rc -eq 1 ]] || ok=0
  has_step "$jl" migrate ok || ok=0
  has_step "$jl" start fail || ok=0
  has_step "$jl" recover_start started || ok=0
  has_step "$jl" recover_start fail || ok=0
  has_step "$jl" lock released || ok=0
  # 数据未回滚：新键分区在、旧键分区不在
  if [[ -d "$sc/data/sessions/$NEW_KEY" && ! -d "$sc/data/sessions/$OLD_KEY" ]]; then :; else ok=0; fi
  [[ -f "$sc/data/maintenance.lock" ]] && ok=0
  if [[ $ok -eq 1 ]]; then
    record B "rc=1 + migrate ok + start fail + recover_start(fail) + 数据保留新布局 + 释放锁" "rc=$rc（$(basename "${jl:-?}")）" PASS
  else
    record B "rc=1 + migrate ok + start fail + recover_start(fail) + 数据保留新布局 + 释放锁" "rc=$rc（分支缺项或数据被误回滚；jsonl: ${jl:-无}）" FAIL
  fi
}

# ═══ 场景 B2：服务忙碌（worker 永不终态）→ 超时变体起服失败 ═══
scen_B2() {
  local sc="$WORK/B2"; local rc=0
  run_orch "$sc" good busy 10 10 >/dev/null 2>&1 || rc=$?
  local jl; jl="$(newest_jsonl "$sc/audit")"
  local ok=1
  [[ $rc -eq 1 ]] || ok=0
  has_step "$jl" start fail || ok=0
  grep -q '"step":"start","status":"fail","detail":"等待终态超时[^"]*且服务未活' "$jl" 2>/dev/null || ok=0
  has_step "$jl" recover_start fail || ok=0
  has_step "$jl" lock released || ok=0
  [[ -f "$sc/data/maintenance.lock" ]] && ok=0
  if [[ $ok -eq 1 ]]; then
    record B2 "rc=1 + 超时起服失败 + 恢复失败 + 释放锁" "rc=$rc（$(basename "${jl:-?}")）" PASS
  else
    record B2 "rc=1 + 超时起服失败 + 恢复失败 + 释放锁" "rc=$rc（未走超时分支或锁残留；jsonl: ${jl:-无}）" FAIL
  fi
}

# ═══ 场景 C：健康检查失败 → 诊断包 + 释放锁 + 非零退出 ═══
scen_C() {
  local sc="$WORK/C"; local rc=0
  run_orch "$sc" good health-fail 20 10 >/dev/null 2>&1 || rc=$?
  local jl; jl="$(newest_jsonl "$sc/audit")"
  local diag; diag="$(ls "$sc/audit"/diag-healthfail-*.txt 2>/dev/null | head -1)"
  local ok=1
  [[ $rc -eq 1 ]] || ok=0
  has_step "$jl" start ok || ok=0        # worker succeeded + pid 活 → 不再"受理即成功"误记
  has_step "$jl" health fail || ok=0
  has_step "$jl" lock released || ok=0
  [[ -n "$diag" ]] || ok=0
  if [[ -n "$diag" ]]; then
    grep -q "web.log 尾部" "$diag" || ok=0
    grep -q "runtime_manifest.web.json" "$diag" || ok=0
  fi
  [[ -f "$sc/data/maintenance.lock" ]] && ok=0
  if [[ $ok -eq 1 ]]; then
    record C "rc=1 + start ok（终态）+ health fail + 诊断包（web.log/manifest/show）+ 释放锁" "rc=$rc（diag: $(basename "$diag")）" PASS
  else
    record C "rc=1 + start ok（终态）+ health fail + 诊断包 + 释放锁" "rc=$rc（诊断包/记录缺项；jsonl: ${jl:-无}; diag: ${diag:-无}）" FAIL
  fi
}

# ═══ 场景 D：SIGTERM → trap 释放锁 ═══
scen_D() {
  local sc="$WORK/D"; local rc=0
  run_orch "$sc" good health-fail 20 240 bg >/dev/null 2>&1 &
  local opid=$!
  local jl="" i
  for i in $(seq 1 40); do # 等 start ok 落账（进入 health 等待窗口）
    sleep 1
    jl="$(newest_jsonl "$sc/audit")"
    [[ -n "$jl" ]] && has_step "$jl" start ok && break
  done
  if [[ -z "$jl" ]] || ! has_step "$jl" start ok; then
    record D "rc=143 + signal 记录 + trap 释放锁" "（等待 start ok 超时；jsonl: ${jl:-无}）" FAIL
    kill -TERM "$opid" 2>/dev/null || true
    wait "$opid" 2>/dev/null || true
    return
  fi
  kill -TERM "$opid" 2>/dev/null || true
  wait "$opid" 2>/dev/null || rc=$?
  local ok=1
  [[ $rc -eq 143 ]] || ok=0
  has_step "$jl" orchestrate signal || ok=0
  has_step "$jl" lock released || ok=0
  [[ -f "$sc/data/maintenance.lock" ]] && ok=0
  if [[ $ok -eq 1 ]]; then
    record D "rc=143 + orchestrate signal + lock released（trap）" "rc=$rc（$(basename "$jl")）" PASS
  else
    record D "rc=143 + orchestrate signal + lock released（trap）" "rc=$rc（trap 未生效/锁残留；jsonl: ${jl:-无}）" FAIL
  fi
}

# ═══ 执行 ═══
decode_to "$WORK/keys.py" "$KEYS_B64"
decode_to "$WORK/gen_env.py" "$ENVGEN_B64"
decode_to "$WORK/svcctl-stub.sh" "$STUB_B64"

log "演练镜像: $WORK（端口 $DRILL_PORT）"
scen_A
scen_B
scen_B2
scen_C
scen_D

# ── 证据归档（jsonl/log/诊断包/verify 输出入仓库审计目录）+ 清理镜像 ──
EVID_DIR="$REPORT_DIR/drill-evidence-$TS"
mkdir -p "$EVID_DIR"
for scdir in "$WORK"/{A,B,B2,C,D}; do
  [[ -d "$scdir" ]] || continue
  tag="$(basename "$scdir")"
  for f in "$scdir"/audit/orchestration-*.jsonl "$scdir"/audit/orchestration-*.log \
           "$scdir"/audit/diag-*.txt "$scdir"/audit/verify-out-*.json; do
    [[ -f "$f" ]] && cp "$f" "$EVID_DIR/$tag-$(basename "$f")"
  done
done
collect_sleep_pids
if [[ "$KEEP" == "1" ]]; then
  log "保留镜像供人工检查: $WORK"
else
  rm -rf "$WORK"
fi

# ── 生产护栏复检 ──
GUARD_OK=1
PROD_ENV_SHA_AFTER="$(shasum -a 256 "$REPO/.env" 2>/dev/null | awk '{print $1}')"
[[ "$PROD_ENV_SHA_BEFORE" == "$PROD_ENV_SHA_AFTER" ]] || GUARD_OK=0
PROD_LOCK_AFTER="absent"; [[ -f "$REPO/data/maintenance.lock" ]] && PROD_LOCK_AFTER="present"
[[ "$PROD_LOCK_BEFORE" == "$PROD_LOCK_AFTER" ]] || GUARD_OK=0
[[ "$PROD_LOCK_AFTER" == "present" ]] && GUARD_OK=0

# ── 报告 ──
mkdir -p "$REPORT_DIR"
{
  printf '# P1-3 编排故障演练报告（%s）\n\n' "$TS"
  printf '演练脚本: scripts/workspace_migration_drill_failures.sh（编排: scripts/workspace_migration_orchestrate.sh R2 修复版）\n\n'
  printf '镜像根: %s | 演练端口: %s | service_control: stub（未触发真实 restart）\n\n' "$WORK" "$DRILL_PORT"
  printf '| 场景 | 期望 | 实测 | 判定 |\n|---|---|---|---|\n'
  for row in "${REPORT_ROWS[@]}"; do printf '%s\n' "$row"; done
  printf '\n生产护栏: .env sha 前后一致=%s | maintenance.lock 前=%s 后=%s（必须 absent）\n\n' \
    "$([[ "$PROD_ENV_SHA_BEFORE" == "$PROD_ENV_SHA_AFTER" ]] && echo PASS || echo FAIL)" \
    "$PROD_LOCK_BEFORE" "$PROD_LOCK_AFTER"
  printf '场景-缺口映射: A=停机前配置预检 | B=起服失败优先恢复服务（+数据不回滚）| B2=服务忙碌超时变体 | C=健康失败诊断包+释放锁 | D=trap 全路径释放锁\n'
  printf '佐证修复2（worker 终态跟踪）: 场景 C 中 start ok 前置条件=worker 终态 succeeded 且 manifest pid 存活（"受理即成功"已消除）。\n'
  printf '\n证据归档: %s（各场景 orchestration jsonl/log/诊断包）\n' "$EVID_DIR"
} >"$REPORT"

log "报告: $REPORT"
if [[ $FAIL_COUNT -eq 0 && $GUARD_OK -eq 1 ]]; then
  log "DRILL ALL PASS（生产护栏 PASS）"
  exit 0
fi
log "DRILL FAILED: 场景失败 $FAIL_COUNT 个；生产护栏 $([[ $GUARD_OK -eq 1 ]] && echo PASS || echo FAIL)"
exit 1
