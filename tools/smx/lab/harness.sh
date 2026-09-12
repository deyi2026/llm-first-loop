#!/usr/bin/env bash
# lab/harness.sh — 阶段二实验编排：fixture 安装 / 客观判定 / 任务卡渲染 / session 定位
# 闸门0冻结件；跑中不改（协议见 PROTOCOL-20260911.md）
set -euo pipefail
LAB="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$LAB/../../.." && pwd)"
SMX="$REPO/tools/smx/smx.py"
DSH_SESSIONS="${DSH_SESSIONS_ROOT:-$REPO/data/dsh-home/sessions}"

usage() { echo "usage: harness.sh setup <T1..T6> <RUNDIR> | judge <T> <RUNDIR> | card <T> <A|B> <RUNDIR> | find-session <RUNDIR> | cleanup-proc <RUNDIR>"; exit 2; }

cmd_setup() {
  local t="$1" d="$2"
  mkdir -p "$d"
  bash "$LAB/tasks/$t/setup.sh" "$d"
  echo "fixture-ready $t $d" >&2
}

cmd_judge() {
  local t="$1" d="$2"
  bash "$LAB/tasks/$t/judge.sh" "$d"
}

cmd_card() {
  local t="$1" cfg="$2" d="$3"
  local body; body="$(cat "$LAB/tasks/$t/task.md")"
  body="${body//\{RUNDIR\}/$d}"
  if [ "$cfg" = "B" ]; then
    local app; app="$(cat "$LAB/tasks/_shared/appendix-B.md")"
    app="${app//\{SMX\}/$SMX}"
    printf '%s\n\n---\n%s\n' "$body" "$app"
  else
    printf '%s\n' "$body"
  fi
}

cmd_find_session() {
  local d="$1" key base
  d="$(cd "$d" && pwd)"
  key="--$(printf '%s' "$d" | sed 's|^/||; s|/|-|g')--"
  base="$DSH_SESSIONS/$key"
  if [ ! -d "$base" ]; then echo "no-session-dir: $base" >&2; exit 1; fi
  ls -dt "$base"/session-* 2>/dev/null | head -3
}

# 判定后清理可能滞留的 fixture 后台进程（仅 T3 writer；按 pid 精确杀）
cmd_cleanup_proc() {
  local d="$1" pidf="$1/out/.writer-pid"
  if [ -f "$pidf" ]; then
    local pid; pid="$(cat "$pidf")"
    kill "$pid" 2>/dev/null || true
    echo "cleaned writer pid=$pid" >&2
  fi
}

[ $# -ge 1 ] || usage
case "$1" in
  setup) shift; [ $# -eq 2 ] || usage; cmd_setup "$@";;
  judge) shift; [ $# -eq 2 ] || usage; cmd_judge "$@";;
  card) shift; [ $# -eq 3 ] || usage; cmd_card "$@";;
  find-session) shift; [ $# -eq 1 ] || usage; cmd_find_session "$@";;
  cleanup-proc) shift; [ $# -eq 1 ] || usage; cmd_cleanup_proc "$@";;
  *) usage;;
esac
