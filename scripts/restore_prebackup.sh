#!/usr/bin/env bash
# P0-E1 工作树搬迁消费端：prebackup 恢复脚本（只消费既有产物，不产出备份）。
#
# 输入契约（legacy 产物；管线不产 LATEST.json）：
#   <dir>/{SHA256SUMS,status.txt,tracked.patch,untracked.tgz,untracked.list.z}
#   可选 head.txt / ahead-behind.txt / extra/ / LATEST.json（有则以它为准，derived=false）。
# 三档：
#   T1 --check          只读检查：git apply --check tracked.patch + untracked 逐条
#                       同名 sha256 比对，列出冲突；不写任何文件。
#   T2 --tracked-only   应用 tracked.patch（git apply 原子性＝失败不留半应用状态；
#                       失败即中止并给出 stash 兜底指引）。
#   T3 --untracked-only 解包 untracked.tgz：同名不同内容不覆盖，写入
#                       <backup_dir>/restored/ 并列出清单；同名同 sha256 跳过（幂等）。
#   默认（无档位旗标）＝ T1 检查通过后依次执行 T2 + T3。
# 目录选择优先级：--dir <path> > 指针文件（LFL_PREBACKUP_LATEST_TXT，默认
#   /tmp/lfl-prebackup-LATEST.txt；支持纯路径或含 "backup_dir" 的 JSON 行）>
#   围栏根下 lfl-prebackup* 目录中 mtime 最新者。
# 路径围栏（硬边界）：realpath 后必须落在 /tmp/lfl-prebackup* 或
#   <repo>/.git/lfl-prebackup/ 之下，否则确定性拒绝。测试可用
#   LFL_PREBACKUP_ROOTS（冒号分隔目录）替换默认围栏根与发现根。
# 幂等：tracked 已应用（git apply --reverse --check 通过）则跳过；untracked
#   同名同内容跳过。重复运行 applied=0、exit 0。
# 退出码：0 ok（含幂等已应用）/ 1 usage·内部错误 / 2 path_outside_fence /
#   3 no_backup_found|dir_missing / 4 conflicts_detected / 5 tracked_apply_failed。
# 最后一行恒为机器可读 JSON 摘要：schema_version/backup_dir/derived/mode/
#   applied/conflicts/reason_code（+ created_at/tracked_state 等扩展字段）。

set -euo pipefail

SCHEMA_VERSION=1
OPT_DIR=""
OPT_CHECK=0
OPT_TRACKED_ONLY=0
OPT_UNTRACKED_ONLY=0
MODE="T2+T3"
REASON="ok"
BACKUP_DIR=""
RAW_DIR=""
DERIVED="true"
CREATED_AT=""
TRACKED_STATE="none"
TRACKED_APPLIED=0
UNTRACKED_RESTORED=0
UNTRACKED_CONFLICTS=0
UNTRACKED_SKIPPED=0
APPLIED_TOTAL=0
CONFLICTS_TOTAL=0
TMP_OUT=""

usage() {
  sed -n '2,27p' "$0"
}

emit_summary() {
  # 机器可读摘要：恒为最后一行（所有退出路径先 emit 再 exit）。
  python3 - "$SCHEMA_VERSION" "$MODE" "$RAW_DIR" "$BACKUP_DIR" "$DERIVED" \
    "$CREATED_AT" "$TRACKED_STATE" "$APPLIED_TOTAL" "$CONFLICTS_TOTAL" "$REASON" <<'PY'
import json, sys
sv, mode, raw, bdir, derived, ca, tstate, applied, conf, reason = sys.argv[1:11]
print(json.dumps({
    "schema_version": int(sv),
    "backup_dir": bdir or None,
    "requested_dir": raw or None,
    "derived": derived == "true",
    "created_at": ca or None,
    "mode": mode,
    "tracked_state": tstate,
    "applied": int(applied),
    "conflicts": int(conf),
    "reason_code": reason,
}, ensure_ascii=False))
PY
}

_realpath() {
  if command -v realpath >/dev/null 2>&1; then
    realpath "$1"
  else
    python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"
  fi
}

if stat -f %m / >/dev/null 2>&1; then
  _mtime() { stat -f %m "$1"; }
else
  _mtime() { stat -c %Y "$1"; }
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || { echo "[restore_prebackup] usage: --dir 需要 <path>" >&2; exit 1; }
      OPT_DIR="$2"; shift 2 ;;
    --check) OPT_CHECK=1; shift ;;
    --tracked-only) OPT_TRACKED_ONLY=1; shift ;;
    --untracked-only) OPT_UNTRACKED_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[restore_prebackup] 未知参数: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if (( OPT_CHECK )); then MODE="T1"
elif (( OPT_TRACKED_ONLY )); then MODE="T2"
elif (( OPT_UNTRACKED_ONLY )); then MODE="T3"
fi

REPO_ROOT="$(git rev-parse --show-toplevel)" || {
  REASON="not_a_git_repo"; echo "[restore_prebackup] 当前目录不在 git 工作树内" >&2
  emit_summary; exit 1
}

fence_ok() {
  local d="$1" r real_root
  if [[ -n "${LFL_PREBACKUP_ROOTS:-}" ]]; then
    for r in ${LFL_PREBACKUP_ROOTS//:/ }; do
      [[ -z "$r" ]] && continue
      real_root="$(_realpath "$r")" || continue
      if [[ "$d" == "$real_root" || "$d" == "$real_root"/* ]]; then return 0; fi
    done
    return 1
  fi
  # macOS：realpath 把 /tmp 规范成 /private/tmp——围栏按 realpath 前缀匹配，
  # 两个拼写都认（Linux 上 realpath(/tmp)==/tmp，二检查一）。
  if [[ "$d" == /tmp/lfl-prebackup* ]]; then return 0; fi
  local tmp_real
  tmp_real="$(_realpath /tmp)"
  if [[ "$tmp_real" != "/tmp" && "$d" == "$tmp_real"/lfl-prebackup* ]]; then return 0; fi
  real_root="$(_realpath "$REPO_ROOT")/.git/lfl-prebackup"
  [[ "$d" == "$real_root" || "$d" == "$real_root"/* ]] && return 0
  return 1
}

discover_dir() {
  local ptr="${LFL_PREBACKUP_LATEST_TXT:-/tmp/lfl-prebackup-LATEST.txt}" line jp
  if [[ -f "$ptr" ]]; then
    line="$(LC_ALL=C tr -d '\r' <"$ptr" | tail -n 1)"
    jp="$(printf '%s' "$line" | sed -n 's/.*"backup_dir"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    if [[ -n "$jp" ]]; then printf '%s' "$jp"; return; fi
    line="$(printf '%s' "$line" | tr -d '[:space:]')"
    if [[ "$line" == /* ]]; then printf '%s' "$line"; return; fi
  fi
  local best="" best_m=-1 m c r g real_root
  local -a cands=()
  if [[ -n "${LFL_PREBACKUP_ROOTS:-}" ]]; then
    for r in ${LFL_PREBACKUP_ROOTS//:/ }; do
      [[ -d "$r" ]] || continue
      [[ "$(basename "$r")" == lfl-prebackup* ]] && cands+=("$r")
      for g in "$r"/lfl-prebackup*; do [[ -d "$g" ]] && cands+=("$g"); done
    done
  else
    for g in /tmp/lfl-prebackup*; do [[ -d "$g" ]] && cands+=("$g"); done
    real_root="$(_realpath "$REPO_ROOT")/.git/lfl-prebackup"
    if [[ -d "$real_root" ]]; then
      for g in "$real_root"/*; do [[ -d "$g" ]] && cands+=("$g"); done
    fi
  fi
  for c in ${cands[@]+"${cands[@]}"}; do
    m="$(_mtime "$c")" || continue
    if (( m > best_m )); then best="$c"; best_m="$m"; fi
  done
  printf '%s' "$best"
}

untracked_pass() {
  # $1=mode(check|apply) $2=tgz $3=repo $4=restored_dir
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import hashlib, os, shutil, sys, tarfile, tempfile

mode, tgz, repo, restored_dir = sys.argv[1:5]
rest = conf = skip = 0

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

with tarfile.open(tgz) as t:
    members = [m for m in t.getmembers() if m.isfile()]
    with tempfile.TemporaryDirectory(prefix="lfl-prebackup-restore-") as st:
        # 审查 P2-1（2026-11-02）：**先验后解**。原实现先 extractall 再逐条查
        # "/" 前缀与 ".."——Python < 3.12 的 filter=None 回退路径下，恶意成员
        # 在解包阶段就已写到临时目录之外（检查太晚）。现在只解安全成员：
        # 越界成员一条都不进 extractall，逐条检查/计数逻辑保持不变。
        safe_members = [
            m
            for m in members
            if not m.name.startswith("/")
            and ".." not in m.name.split("/")
            and not m.name.startswith("__MACOSX/")
        ]
        try:
            t.extractall(st, members=safe_members, filter="data")
        except TypeError:  # Python < 3.12 无 filter 参数
            t.extractall(st, members=safe_members)
        for m in members:
            name = m.name
            if name.startswith("__MACOSX/") or os.path.basename(name).startswith("._"):
                skip += 1
                print(f"appledouble-skip: {name}")
                continue
            parts = name.split("/")
            if name.startswith("/") or ".." in parts:
                conf += 1
                print(f"UNSAFE-ENTRY(reject): {name}")
                continue
            src = os.path.join(st, name)
            dst = os.path.join(repo, name)
            if os.path.exists(dst):
                if sha256(src) == sha256(dst):
                    skip += 1
                    print(f"same(skip): {name}")
                else:
                    conf += 1
                    print(f"conflict: {name}")
                    if mode == "apply":
                        out = os.path.join(restored_dir, name)
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        shutil.copy2(src, out)
                        print(f"conflict-saved: {restored_dir}/{name}")
            else:
                print(f"{'would-restore' if mode == 'check' else 'restored'}: {name}")
                if mode == "apply":
                    d = os.path.dirname(dst)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    shutil.copy2(src, dst)
                    rest += 1
print(f"UNTRACKED_COUNTS {rest} {conf} {skip}")
PY
}

trap '[ -n "$TMP_OUT" ] && rm -f "$TMP_OUT"' EXIT

RAW_DIR="$OPT_DIR"
if [[ -z "$RAW_DIR" ]]; then
  RAW_DIR="$(discover_dir)"
fi
if [[ -z "$RAW_DIR" ]]; then
  REASON="no_backup_found"
  echo "[restore_prebackup] 未找到任何 prebackup（--dir/指针/发现根均无）" >&2
  emit_summary; exit 3
fi

BACKUP_DIR="$(_realpath "$RAW_DIR")"
if ! fence_ok "$BACKUP_DIR"; then
  REASON="path_outside_fence"
  echo "[restore_prebackup] REJECT path_outside_fence: $BACKUP_DIR 不在允许根内（/tmp/lfl-prebackup* 或 <repo>/.git/lfl-prebackup/ 或 LFL_PREBACKUP_ROOTS）" >&2
  emit_summary; exit 2
fi
if [[ ! -d "$BACKUP_DIR" ]]; then
  REASON="dir_missing"
  echo "[restore_prebackup] 备份目录不存在: $BACKUP_DIR" >&2
  emit_summary; exit 3
fi

if [[ -f "$BACKUP_DIR/LATEST.json" ]]; then
  CREATED_AT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("created_at","") or "")' "$BACKUP_DIR/LATEST.json")" || CREATED_AT=""
  [[ -n "$CREATED_AT" ]] && DERIVED="false"
fi
if [[ -z "$CREATED_AT" ]]; then
  CREATED_AT="$(python3 -c 'import datetime,sys; print(datetime.datetime.fromtimestamp(int(sys.argv[1])).astimezone().isoformat(timespec="seconds"))' "$(_mtime "$BACKUP_DIR")")"
fi

PATCH="$BACKUP_DIR/tracked.patch"
TGZ="$BACKUP_DIR/untracked.tgz"

echo "[restore_prebackup] mode=$MODE repo=$REPO_ROOT backup_dir=$BACKUP_DIR derived=$DERIVED created_at=$CREATED_AT"

# ---- T1: tracked 只读检查（幂等态优先判定） ----
if [[ -f "$PATCH" ]]; then
  if git -C "$REPO_ROOT" apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    TRACKED_STATE="already_applied"
    echo "T1: tracked.patch 已应用（幂等跳过）"
  elif git -C "$REPO_ROOT" apply --check "$PATCH" >/dev/null 2>&1; then
    TRACKED_STATE="clean_apply"
    echo "T1: tracked.patch 可干净应用"
  else
    TRACKED_STATE="conflict"
    echo "T1: tracked.patch 存在冲突（git apply --check 失败）："
    git -C "$REPO_ROOT" apply --check "$PATCH" || true
  fi
else
  echo "T1: 无 tracked.patch"
fi

# ---- T1: untracked 只读比对（--check 到此结束） ----
if [[ "$MODE" == "T1" && -f "$TGZ" ]]; then
  TMP_OUT="$(mktemp)"
  untracked_pass check "$TGZ" "$REPO_ROOT" "$BACKUP_DIR/restored" >"$TMP_OUT" || {
    cat "$TMP_OUT"; REASON="internal_error"; emit_summary; exit 1
  }
  cat "$TMP_OUT"
  read -r _ UNTRACKED_RESTORED UNTRACKED_CONFLICTS UNTRACKED_SKIPPED <<<"$(tail -n 1 "$TMP_OUT")"
  rm -f "$TMP_OUT"; TMP_OUT=""
  if [[ "$TRACKED_STATE" == "conflict" ]]; then
    CONFLICTS_TOTAL=$(( UNTRACKED_CONFLICTS + 1 ))
  else
    CONFLICTS_TOTAL="$UNTRACKED_CONFLICTS"
  fi
  if (( CONFLICTS_TOTAL > 0 )); then REASON="conflicts_detected"; fi
  emit_summary
  if (( CONFLICTS_TOTAL == 0 )); then exit 0; else exit 4; fi
fi

# ---- T2: 应用 tracked.patch ----
if [[ "$MODE" == "T2" || "$MODE" == "T2+T3" ]]; then
  if [[ -f "$PATCH" ]]; then
    case "$TRACKED_STATE" in
      clean_apply)
        if git -C "$REPO_ROOT" apply "$PATCH"; then
          TRACKED_APPLIED=1
          echo "T2: tracked.patch 已应用（git apply 原子性：失败不留半应用状态）"
        else
          REASON="tracked_apply_failed"
          echo "T2: tracked.patch 应用失败，已中止（不执行 T3；工作树保持应用前状态）" >&2
          echo "    stash 兜底：git stash list 查看；备份含 stash_ref <ref> 时可 git stash apply <ref>" >&2
          emit_summary; exit 5
        fi ;;
      already_applied) echo "T2: 已应用，跳过（幂等）" ;;
      conflict)
        REASON="tracked_apply_failed"
        echo "T2: T1 预检即冲突，中止（不执行 T3；工作树保持原状）" >&2
        echo "    stash 兜底：git stash list 查看；备份含 stash_ref <ref> 时可 git stash apply <ref>" >&2
        emit_summary; exit 5 ;;
      none) echo "T2: 无 tracked.patch，跳过" ;;
    esac
  else
    echo "T2: 无 tracked.patch，跳过"
  fi
fi

# ---- T3: 解包 untracked ----
if [[ "$MODE" == "T3" || "$MODE" == "T2+T3" ]]; then
  if [[ -f "$TGZ" ]]; then
    TMP_OUT="$(mktemp)"
    untracked_pass apply "$TGZ" "$REPO_ROOT" "$BACKUP_DIR/restored" >"$TMP_OUT" || {
      cat "$TMP_OUT"; REASON="internal_error"; emit_summary; exit 1
    }
    cat "$TMP_OUT"
    read -r _ UNTRACKED_RESTORED UNTRACKED_CONFLICTS UNTRACKED_SKIPPED <<<"$(tail -n 1 "$TMP_OUT")"
    rm -f "$TMP_OUT"; TMP_OUT=""
    CONFLICTS_TOTAL="$UNTRACKED_CONFLICTS"
    if (( CONFLICTS_TOTAL > 0 )); then
      REASON="conflicts_detected"
      echo "T3: $CONFLICTS_TOTAL 个同名不同内容文件未覆盖，已写入 $BACKUP_DIR/restored/（见 conflict-saved 清单）" >&2
    fi
  else
    echo "T3: 无 untracked.tgz，跳过"
  fi
fi

APPLIED_TOTAL=$(( TRACKED_APPLIED + UNTRACKED_RESTORED ))
emit_summary
if [[ "$REASON" == "conflicts_detected" ]]; then exit 4; fi
exit 0
