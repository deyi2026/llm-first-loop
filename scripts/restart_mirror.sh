#!/usr/bin/env bash
# restart_mirror.sh — 唯一工作区常驻服务重启脚本（2026-08-22 实践整理；2026-09-29 主区退役，本区即唯一区）
#
# 拓扑现状（2026-09-29，用户指示）: 原主区（同级 llm-first-loop 目录，:8902）已物理删除，
#   变更门禁见 docs/WORKSPACE-CHANGE-PROTOCOL.md。下方各条“旧主区”注意事项为历史事故实证记录，
#   其防御机制（精确端口匹配/环境清理/PYTHONPATH 归零）保留为纵深防御，勿删。
#
# 管理本工作区常驻服务:
#   web    FastAPI 服务（python -m llm_loop.web，端口 8903，公开就绪端点 GET /auth/status）
#   feishu 飞书桥（python -m llm_loop.feishu，WS 长连接 msg-frontier.feishu.cn）
#
# ⚠️⚠️ 最重要注意事项 ⚠️⚠️
#   1. 切勿用 `pkill -f "llm_loop.web"` —— 会把旧主区 web（:8902）一起杀掉！
#      （旧主区/镜像进程命令行相同，pkill 全匹配无法区分。实证 2026-08-22 误杀旧主区）
#      正确做法: 按端口杀（lsof -tiTCP:$PORT），本脚本已内置。
#   2. 必须先 `source .env` 再启动 —— 进程 env 才能读到配置
#      （不 source 则 TOOL_ROUND_ZERO_HISTORY 等配置缺失/旧值。实证 2026-08-22）
#   3. PYTHONPATH 必须指向镜像 src —— 否则 editable install 会加载旧主区代码
#      （镜像跑旧主区代码 = 验证失真。实证 2026-08-22 镜像慢/行为不一致）
#   4. WEB_PORT=8903 必须显式设置 —— 否则默认 8902 与旧主区冲突
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
# 权威入口（L16）：生命周期变更的唯一权威路径是 service_control
#   （工具 action=restart|update，或 `python -m llm_loop.runtime.service_control
#   restart`）；其 worker 注入 LFL_RESTART_ACTION_ID。直连本脚本无该变量，属
#   非权威应急通道——回执标注 authority=direct-non-authoritative 并指向权威入口。
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
#   修6 Web V2 产物/就绪闭环: web/all 在停旧服务前检查 gitignored webui/dist
#       及 index 引用资源；启动后同时验 /auth/status 与 /ui/v2，禁止后端绿但页面404假成功。
#   修7 就绪预算 30s→90s、语义改为墙钟秒（2026-10-20 实证：gen292 部署冷启动
#       30.7s 判负 → 控制面自动回滚 gen293）；成功/失败均记录 elapsed，
#       LFL_WEB_READY_TIMEOUT_S 可覆盖。

set -euo pipefail

# Gate E dual-root: operational state/config may remain on the canonical mirror root
# while an exact clean linked worktree supplies the code bytes.  With no overrides,
# both roots collapse to SCRIPT_ROOT and historical behavior is byte-for-byte in scope.
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
_resolve_root() {
  local raw="$1" label="$2"
  [[ -d "$raw" ]] || { echo "[mirror] ✗ $label 不存在: $raw" >&2; return 2; }
  (cd "$raw" && pwd -P)
}
RUNTIME_ROOT="$(_resolve_root "${LFL_RESTART_RUNTIME_ROOT:-$SCRIPT_ROOT}" RUNTIME_ROOT)"
CODE_ROOT="$(_resolve_root "${LFL_RESTART_CODE_ROOT:-$SCRIPT_ROOT}" CODE_ROOT)"
MIRROR_DIR="$RUNTIME_ROOT"  # compatibility alias: every operational path stays canonical
DUAL_ROOT=0
[[ "$RUNTIME_ROOT" != "$CODE_ROOT" ]] && DUAL_ROOT=1
RESTART_ARG1="${1:-web}"  # S1(2026-09-22): 函数内 $1 被遮蔽；根检查中止的回执需要脚本目标
# P1-3(2026-10-25): 默认工作区根（AI 默认可写区）。与 LFL_WORKSPACE_ROOT（代码
# 身份锚，指向 $CODE_ROOT 不可改）语义无关；下方三处 spawn 前缀注入同名变量。
LFL_DEFAULT_WORKSPACE_ROOT="${LFL_DEFAULT_WORKSPACE_ROOT:-$HOME/lfl-workspace}"

# ── lifecycle_agency：结构化阶段事实 + 模型举证推进（tasks 3.1 / 2.3 / 5.x）──
# STAGE_FACT: 结构化阶段事实（L4 取代 marker 白名单推断副作用）。worker 只读该
#   字段判断"本次失败是否零物理副作用"，不再猜测 detail 文本。
#   not_started → web_stopped/feishu_stopped/learning_stopped → started
# OVERRIDE_GATES: worker 注入的、经模型结构化出口举证推进的一致性门禁（逗号
#   分隔）。仅 consistency 类门禁可被列出；physical_impossible/identity_conflict
#   永不出现在此（worker 侧已在 record_model_override 拒穿透）。
LFL_RESTART_STAGE_FACT="${LFL_RESTART_STAGE_FACT:-not_started}"
export LFL_RESTART_STAGE_FACT
_override_enabled() {  # $1=gate
  [[ ",${LFL_RESTART_OVERRIDE_GATES:-}," == *",$1,"* ]]
}

# ── 单一权威生命周期入口（tasks 8.1 / L16）──
# 唯一权威路径是 service_control 工具/CLI：其 worker 注入 LFL_RESTART_ACTION_ID。
# 直连本脚本（无 action_id）是合法操作员应急通道，但**非权威**——回执显式标注
# 并指向权威入口，模型/自动化路径不得以直连为前置条件（spec 4.3-4）。此处只做
# 事实标注，不新增拦截门禁（Admission asymmetry：不得增设控制机械）。
LFL_RESTART_ACTION_ID="${LFL_RESTART_ACTION_ID:-}"
if [[ -n "$LFL_RESTART_ACTION_ID" ]]; then
  RESTART_AUTHORITY="service_control"
else
  RESTART_AUTHORITY="direct-non-authoritative"
fi
export LFL_RESTART_AUTHORITY="$RESTART_AUTHORITY"

# ── T0-A3（2026-09-16；R4 2026-09-22 扩展到 RUNTIME_ROOT；S2 2026-09-22 降级同仓族）──
# 当日事故根因: 会话环境残留 LFL_RESTART_CODE_ROOT 指向旧 worktree，脚本静默
# 加载旧代码（service_control 缺失才暴露）。R4 扩展: ambient
# LFL_RESTART_RUNTIME_ROOT 同样能污染预检根。四态来源:
#   ① 调用点显式（环境值==脚本目录，或 CONFIRMED=1）→ 通过
#   ② 脚本目录默认（未设环境变量）→ 通过
#   ③ 同仓族覆盖（环境值≠脚本目录，但 --git-common-dir 与脚本同仓）→ 告警+
#      审计 outcome=deferred-to-verify，放行，裁决移交 service-control 部署
#      绑定核验（P0-A 字节级；残留指向未发布 worktree 时 verify 必拒）
#   ④ 异仓族/无 Git 身份（跨区、跨仓、临时目录）→ 结构上不可能被本仓部署
#      存储授权 → 告警+审计；自动化通道（非 tty 或 FORCE=1）直接 abort
# S2 裁决依据（2026-09-22 13:20 事故）：受控 dual-root 重启与残留共用「环境根
# ≠脚本目录」形态，CONFIRMED 硬门把滚动升级（旧控制器不带 CONFIRMED × 新
# 脚本）砖死；同仓族放行 + verify 裁决后，任意升级顺序都自洽。受控路径
# （service_control worker）注入的 CONFIRMED 对继续生效（来源①），兼容不回撤。
_same_git_family() {  # $1=candidate root：与 SCRIPT_ROOT 同 git 仓族（linked worktree）
  local cand_common script_common
  cand_common="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$cand_common" ]] || return 1
  cand_common="$(cd "$cand_common" 2>/dev/null && pwd -P)" || return 1
  script_common="$(git -C "$SCRIPT_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$script_common" ]] || return 1
  script_common="$(cd "$script_common" 2>/dev/null && pwd -P)" || return 1
  [[ "$cand_common" == "$script_common" ]]
}
_root_source_defer_audit() {  # $1=env_var
  mkdir -p "$MIRROR_DIR/data/audit" 2>/dev/null || true
  printf '%s code_root_source=same-repo-defer var=%s code_root=%s runtime_root=%s script_root=%s outcome=deferred-to-verify\n' \
    "$(date '+%FT%T')" "$1" "$CODE_ROOT" "$RUNTIME_ROOT" "$SCRIPT_ROOT" \
    >> "$MIRROR_DIR/data/audit/restart_preflight.log" 2>/dev/null || true
}
_root_source_check() {  # $1=env_var $2=resolved_value $3=label $4=confirm_var
  local env_var="$1" value="$2" label="$3" confirm_var="$4"
  [[ -n "${!env_var:-}" && "$value" != "$SCRIPT_ROOT" ]] || return 0
  if [[ "${!confirm_var:-0}" == "1" ]]; then
    echo "[mirror] $(date '+%H:%M:%S')    ${confirm_var}=1 显式确认, 继续"
    return 0
  fi
  # S2: 同仓族覆盖 → 告警放行，verify 裁决（见上方四态来源 ③）
  if _same_git_family "$value"; then
    echo "[mirror] $(date '+%H:%M:%S') [A3-INFO] $label 来自环境变量 $env_var=${value}（≠脚本目录 ${SCRIPT_ROOT}，但同 Git 仓族）——告警放行，裁决移交 service-control 部署绑定核验"
    _root_source_defer_audit "$env_var"
    return 0
  fi
  echo "[mirror] $(date '+%H:%M:%S') [A3-RESIDUE] $label 来自环境变量 $env_var=${value}（≠脚本目录 ${SCRIPT_ROOT}，且异仓族/无 Git 身份）——疑似跨区/跨仓污染"
  if [[ -t 0 && "${FORCE:-0}" != "1" ]]; then
    printf '确认使用环境变量指定的 %s? (y/N) ' "$label"
    read -r _confirm_ans
    if [[ "$_confirm_ans" =~ ^[yY]$ ]]; then
      echo "[mirror] $(date '+%H:%M:%S')    交互确认通过"
      return 0
    fi
    echo "[mirror] $(date '+%H:%M:%S') 已取消（$label 来源未确认）"
    return 2
  fi
  # lifecycle_agency L11/5.3: 根来源残留属 consistency——模型经结构化出口
  # override(gate=precheck:root_source) 举证推进后仅作告警证据，不再硬拒。
  if _override_enabled precheck:root_source; then
    echo "[mirror] $(date '+%H:%M:%S') [A3-OVERRIDE] $label 残留已由模型举证推进（precheck:root_source），告警放行、裁决移交 verify"
    _root_source_defer_audit "$env_var"
    return 0
  fi
  echo "[mirror] $(date '+%H:%M:%S') [A3-RESIDUE] 自动化通道检测到异仓族环境根 $label 且未显式确认, 拒绝重启"
  echo "[mirror] $(date '+%H:%M:%S')    修复: 调用点显式 export ${env_var}=<目标> 并加 ${confirm_var}=1，或经 service_control(action=override, gate=precheck:root_source, ...) 举证推进"
  return 2
}
_code_root_source_check() {
  _root_source_check LFL_RESTART_CODE_ROOT "$CODE_ROOT" CODE_ROOT LFL_RESTART_CODE_ROOT_CONFIRMED
}
_runtime_root_source_check() {
  _root_source_check LFL_RESTART_RUNTIME_ROOT "$RUNTIME_ROOT" RUNTIME_ROOT LFL_RESTART_RUNTIME_ROOT_CONFIRMED
}
_root_source_abort() {  # $1=triggering_var
  mkdir -p "$MIRROR_DIR/data/audit" 2>/dev/null || true
  printf '%s code_root_source=env-residue var=%s code_root=%s runtime_root=%s script_root=%s outcome=aborted\n' \
    "$(date '+%FT%T')" "$1" "$CODE_ROOT" "$RUNTIME_ROOT" "$SCRIPT_ROOT" \
    >> "$MIRROR_DIR/data/audit/restart_preflight.log" 2>/dev/null || true
  # S1(2026-09-22): 变更目标的中止必须落 R1 白名单回执——worker 据此自动释放
  # 屏障；不写回执则按"无回执 fail-closed"keep，零副作用中止被卡成死窗
  # （2026-09-22 13:20 事故实证）。只读目标（preflight/status）保持零写入。
  case "$RESTART_ARG1" in
    web|feishu|learning|all) _write_receipt "$RESTART_ARG1" 2 "root_source_aborted" ;;
  esac
  exit 2
}
# 调用点在预检链末端（case 之前）——S1(2026-09-22) 从文件头部移入：
# 原位置早于 _write_receipt 定义，中止路径无法履行回执义务。

_validate_restart_roots() {
  [[ "$DUAL_ROOT" -eq 1 ]] || return 0
  # 根结构完整性/身份类 = identity_conflict：不可 override 穿透（design 2.1.3.2）。
  [[ -x "$RUNTIME_ROOT/.venv/bin/python" ]] || { echo "[mirror] ✗ dual-root 拒绝(identity): runtime .venv 缺失" >&2; return 2; }
  [[ -f "$RUNTIME_ROOT/.env" ]] || { echo "[mirror] ✗ dual-root 拒绝(identity): runtime .env 缺失" >&2; return 2; }
  [[ -d "$CODE_ROOT/src/llm_loop" ]] || { echo "[mirror] ✗ dual-root 拒绝(identity): code src/llm_loop 缺失" >&2; return 2; }

  local runtime_common code_common dirty
  runtime_common="$(git -C "$RUNTIME_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  code_common="$(git -C "$CODE_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  [[ -n "$runtime_common" && -n "$code_common" ]] || { echo "[mirror] ✗ dual-root 拒绝(identity): root 必须都是 Git worktree" >&2; return 2; }
  runtime_common="$(cd "$runtime_common" 2>/dev/null && pwd -P)" || return 2
  code_common="$(cd "$code_common" 2>/dev/null && pwd -P)" || return 2
  [[ "$runtime_common" == "$code_common" ]] || { echo "[mirror] ✗ dual-root 拒绝(identity): git-common-dir 不一致" >&2; return 2; }
  git -C "$CODE_ROOT" rev-parse --verify HEAD >/dev/null 2>&1 || { echo "[mirror] ✗ dual-root 拒绝(identity): CODE_ROOT HEAD 不可解析" >&2; return 2; }

  # 以下为 consistency 类（L10/5.1）：不再是唯一出路，模型可经结构化出口
  # override(gate=precheck:dual_root) 附证据推进；未推进时才硬拒。
  dirty="$(git -C "$CODE_ROOT" status --porcelain --untracked-files=normal 2>/dev/null || echo __git_status_failed__)"
  if [[ -n "$dirty" ]]; then
    if _override_enabled precheck:dual_root; then
      echo "[mirror] [OVERRIDE] CODE_ROOT 树脏已由模型举证推进（precheck:dual_root），告警放行" >&2
    else
      echo "[mirror] ✗ dual-root 拒绝(consistency): CODE_ROOT 必须 clean" >&2
      return 2
    fi
  fi

  # T0-A2(2026-09-16): CODE_ROOT 内含嵌套 worktree——嵌套目录会弄脏 dual-root
  # clean 校验并阻断部署（当日事故形态: 判基线 worktree 误建于现役 code root
  # 内部）。预防: scripts/bootstrap_worktree_registry.py --check-add。
  local nested_wt
  nested_wt="$(git -C "$CODE_ROOT" worktree list --porcelain 2>/dev/null | awk -v root="$CODE_ROOT" '$1=="worktree"{p=substr($0,10); if (p!=root && index(p, root"/")==1) print p}')"
  if [[ -n "$nested_wt" ]]; then
    if _override_enabled precheck:dual_root; then
      echo "[mirror] [OVERRIDE] CODE_ROOT 嵌套 worktree 已由模型举证推进（precheck:dual_root）: $nested_wt" >&2
    else
      echo "[mirror] ✗ dual-root 拒绝(consistency): CODE_ROOT 内含嵌套 worktree: $nested_wt" >&2
      echo "[mirror]   先 git worktree remove 后重启，或 override(precheck:dual_root)" >&2
      return 2
    fi
  fi
}
# 调用点在预检链末端（S1 移入，与根来源判定同因：中止路径需 _write_receipt 已定义）。
cd "$RUNTIME_ROOT"

VENV_PY="$RUNTIME_ROOT/.venv/bin/python"
# R2（RUNTIME-SOT-WIRE）: 业务配置经 runtime resolver 查询（.env 权威 + 跨区污染
# 防御——外部 shell 残留 WEB_PORT=8902 不压过镜像 .env 的 8903）。
# 修复(2026-08-29): ①查询必须带 PYTHONPATH=镜像 src——shell 环境常残留旧主区 PYTHONPATH
# （DSH harness 注入），不带则跑旧主区 resolver 对镜像语义输出空、exit 0；
# ②成功但输出为空也要兜底——$(cmd || echo x) 只兜命令失败兜不了空串成功
# （实证: WEB_PORT="" → "port 无监听进程"假停机 + 新进程绑 8903 撞旧进程 Errno 48）。
WEB_PORT="$(LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" -m llm_loop.runtime.resolver WEB_PORT 2>/dev/null || true)"
WEB_PORT="${WEB_PORT:-8903}"
WEB_HOST="$(LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" -m llm_loop.runtime.resolver WEB_HOST 2>/dev/null || true)"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
# RESTART_PORT: 冻结端口值——_start_web/_start_feishu 内部会 unset WEB_PORT/WEB_HOST
# （防启动 shell 残留值压过 .env），但 case 分支与回执在启动之后仍需端口值
# （set -u 下引用已 unset 变量会中断脚本）。独立变量在 top-level 冻结，不受影响。
RESTART_PORT="$WEB_PORT"

_log() { echo "[mirror] $(date '+%H:%M:%S') $*"; }

# Endpoint queries are value channels; diagnostics must never reach stop/start.
_web_endpoint_preflight() {
  if [[ ! "$RESTART_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$RESTART_PORT < 1 || 10#$RESTART_PORT > 65535 )); then
    _log "❌ Web 端口解析无效，拒绝停止服务: $RESTART_PORT"
    return 1
  fi
}

# P0-A shared-service lifecycle authority: mutating restarts require an
# operator-published desired deployment that exactly binds code/runtime roots and
# tracked Git identity. Web/all also bind the ignored WebUI artifact tree. This is
# checked before any healthy service is stopped.
_service_control_preflight() {
  local target="$1"
  local rc=0
  if [[ "$target" == "feishu" || "$target" == "learning" ]]; then
    LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" \
      "$VENV_PY" -m llm_loop.runtime.service_control verify \
      --data-dir "$RUNTIME_ROOT/data" \
      --code-root "$CODE_ROOT" \
      --runtime-root "$RUNTIME_ROOT" --skip-webui || rc=$?
  else
    LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" \
      "$VENV_PY" -m llm_loop.runtime.service_control verify \
      --data-dir "$RUNTIME_ROOT/data" \
      --code-root "$CODE_ROOT" \
      --runtime-root "$RUNTIME_ROOT" || rc=$?
  fi
  if [[ "$rc" -eq 0 ]]; then
    _log "✅ service-control desired deployment binding PASS ($target)"
    return 0
  fi
  _log "✗ service-control desired deployment binding FAILED；拒绝停止现有服务"
  _log "  首次/新版本部署需先由 operator publish exact desired generation"
  return 1
}

# Web V2 build artifacts are intentionally gitignored. A fresh linked worktree may
# therefore contain exact Python/source bytes but no webui/dist, in which case
# create_app() does not mount /ui/v2 at all. Fail before stopping a healthy Web.
_webui_artifact_preflight() {
  local dist="${UI_V2_DIR:-$CODE_ROOT/webui/dist}"
  local index="$dist/index.html"
  if [[ ! -f "$index" ]]; then
    if _override_enabled precheck:artifact; then
      _log "⚠️ [OVERRIDE] Web V2 产物缺失已由模型举证推进（precheck:artifact）: $index 不存在，告警放行"
      return 0
    fi
    _log "✗ Web V2 artifact preflight failed: $index 不存在"
    _log "  缺失清单: index.html 缺失；下一步: cd '$CODE_ROOT/webui' && npm run build（或 service_control action=update）"
    return 1
  fi

  # Validate every local /ui/v2/... reference emitted by the built index. This
  # catches partial/stale copies (index exists but hashed JS/CSS/font/favicon is
  # missing) before any running service is stopped.
  if ! "$VENV_PY" - "$dist" <<'PYASSET'
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

root = Path(sys.argv[1]).resolve()
index = root / "index.html"

class Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith("/ui/v2/"):
                path = urlsplit(value).path.removeprefix("/ui/v2/")
                if path:
                    self.refs.add(path)

parser = Refs()
parser.feed(index.read_text(encoding="utf-8"))
missing = [ref for ref in sorted(parser.refs) if not (root / ref).is_file()]
if missing:
    for ref in missing:
        print(f"missing Web V2 asset: {ref}", file=sys.stderr)
    raise SystemExit(1)
PYASSET
  then
    if _override_enabled precheck:artifact; then
      _log "⚠️ [OVERRIDE] Web V2 引用资源缺失已由模型举证推进（precheck:artifact），告警放行"
      return 0
    fi
    _log "✗ Web V2 artifact preflight failed: index 引用的静态资源缺失（缺失清单见上方 'missing Web V2 asset:' 行）"
    _log "  下一步: cd '$CODE_ROOT/webui' && npm run build（或 service_control action=update）"
    return 1
  fi
  # Index + hashed filenames alone do NOT prove that the bundle was built
  # from this checkout. Gen264 served pre-fix JS/CSS with post-fix tracked JSX.
  # Check the build-produced exact source fingerprint before any Web stop.
  if [[ -f "$CODE_ROOT/webui/package.json" ]]; then
    if ! PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" - "$CODE_ROOT" "$dist" <<'PYSOURCE'
import sys
from pathlib import Path
from llm_loop.runtime.webui_provenance import verify_webui_source_binding

try:
    verify_webui_source_binding(
        Path(sys.argv[1]).resolve(), dist_root=Path(sys.argv[2]).resolve()
    )
except (OSError, ValueError) as exc:
    print(f"webui artifact source binding rejected: {exc}", file=sys.stderr)
    raise SystemExit(1)
PYSOURCE
    then
      if _override_enabled precheck:artifact; then
        _log "⚠️ [OVERRIDE] Web V2 source binding 由模型显式举证放行 (precheck:artifact)"
      else
        _log "✗ Web V2 artifact source binding FAILED；拒绝停止现有 Web"
        _log "  下一步: 在当前固定代码版本的 webui/ 运行 npm run build，再由 operator publish"
        return 1
      fi
    fi
  fi
  _log "✅ Web V2 artifact preflight PASS: $dist"
}

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
_web_run_busy() {
  PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" - "$RUNTIME_ROOT/data/sessions" <<'PY' 2>/dev/null
import sys
from pathlib import Path

from llm_loop.resources.foreground import active_run_locks

busy = active_run_locks(Path(sys.argv[1]))
if busy:
    labels = []
    for path in busy[:4]:
        name = path.name
        if name.endswith(".run.lock"):
            name = name[:-9]
        labels.append(name[:12])
    suffix = ",..." if len(busy) > 4 else ""
    print("web-runs:%d[%s%s]" % (len(busy), ",".join(labels), suffix))
PY
}
_web_run_recovery_ready() {
  PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" - "$RUNTIME_ROOT/data/sessions" "$RUNTIME_ROOT/data/event_logs" <<'PY' 2>/dev/null
import sys
from pathlib import Path

from llm_loop.event_log.store import EventStore
from llm_loop.resources.foreground import active_run_locks

sessions_dir = Path(sys.argv[1])
event_dir = Path(sys.argv[2])
store = EventStore(event_dir)
missing = []
facts = []
for lock_path in active_run_locks(sessions_dir):
    name = lock_path.name
    sid = name[:-9] if name.endswith(".run.lock") else lock_path.stem
    events = store.read_cached(sid)
    last_end = max((i for i, event in enumerate(events) if event.type == "run.end"), default=-1)
    open_events = events[last_end + 1 :]
    checkpoints = [event for event in open_events if event.type == "llm.partial_checkpoint"]
    if not checkpoints:
        missing.append(sid)
        continue
    facts.append(f"{sid[:12]}:cp{checkpoints[-1].seq}")
if missing:
    print("missing-open-checkpoint:" + ",".join(sid[:12] for sid in missing))
    raise SystemExit(1)
if facts:
    print("recovery-ready[" + ",".join(facts) + "]")
PY
}
_restart_busy() {
  local target="${1:-all}" hb="" runs="" parts=""
  if [[ "$target" == "feishu" || "$target" == "all" ]]; then
    hb="$(_heartbeat_busy)"
  fi
  if [[ "$target" == "web" || "$target" == "all" ]]; then
    runs="$(_web_run_busy)"
  fi
  [[ -n "$hb" ]] && parts="$hb"
  if [[ -n "$runs" ]]; then
    [[ -n "$parts" ]] && parts="$parts "
    parts="${parts}${runs}"
  fi
  printf '%s' "$parts"
}
_restart_precheck() {
  local target="${1:-all}" waited=0 busy run_busy
  if [[ "${RESTART_WAIT_IDLE:-0}" == "1" ]]; then
    local idle_timeout="${RESTART_WAIT_IDLE_TIMEOUT_S:-300}" idle_poll="${RESTART_WAIT_IDLE_POLL_S:-5}"
    while :; do
      busy="$(_restart_busy "$target")"
      if [[ -z "$busy" ]]; then
        (( waited > 0 )) && _log "目标服务已无活跃任务（等待 ${waited}s），继续重启"
        return 0
      fi
      if (( waited >= idle_timeout )); then
        _log "等待空闲超时（${waited}s ≥ ${idle_timeout}s），回退确认流程"
        break
      fi
      _log "检测到活跃任务（${busy}），等待任务完成（${waited}/${idle_timeout}s）..."
      sleep "$idle_poll"
      (( waited += idle_poll ))
    done
  fi
  busy="$(_restart_busy "$target")"
  [[ -z "$busy" ]] && return 0
  run_busy=""
  if [[ "$target" == "web" || "$target" == "all" ]]; then
    run_busy="$(_web_run_busy)"
  fi
  _log "⚠️ 检测到活跃任务（${busy}）——重启会中断正在运行的流/任务。"
  if [[ -n "$run_busy" && "${RESTART_FORCE_ACTIVE_RUNS:-0}" != "1" ]]; then
    # L9/5.1: active_run_precheck 属 consistency——模型经结构化出口
    # override(gate=precheck:active_run) 举证后可推进；未举证才 fail-closed。
    if _override_enabled precheck:active_run; then
      _log "⚠️ [OVERRIDE] Web active run 已由模型举证推进（precheck:active_run），继续重启"
      return 0
    fi
    _log "✗ Web active run fail-closed：即使 FORCE=1 也拒绝硬切。仅紧急人工裁决可额外设置 RESTART_FORCE_ACTIVE_RUNS=1，或经 service_control(action=override, gate=precheck:active_run, ...) 举证推进。"
    return 1
  fi
  if [[ -n "$run_busy" && "${RESTART_FORCE_ACTIVE_RUNS:-0}" == "1" ]]; then
    local recovery_ready
    if ! recovery_ready="$(_web_run_recovery_ready)"; then
      _log "✗ 紧急强切拒绝：active run 缺少 open llm.partial_checkpoint（${recovery_ready:-unknown}）。"
      return 1
    fi
    _log "紧急强切恢复证据已核验：${recovery_ready}"
  fi
  if [[ "${FORCE:-0}" == "1" ]]; then
    _log "FORCE=1：跳过交互确认，强制继续（无 Web active run，或已显式 RESTART_FORCE_ACTIVE_RUNS=1）"
    return 0
  fi
  if _override_enabled precheck:active_run; then
    _log "⚠️ [OVERRIDE] 活跃任务已由模型举证推进（precheck:active_run），跳过交互确认"
    return 0
  fi
  echo -n "确认继续重启? (y/N) "
  read -r ans
  if [[ ! "$ans" =~ ^[yY]$ ]]; then
    _log "已取消重启（保护进行中的长任务）。"
    exit 1
  fi
}

# LFL/DSH 服务运行身份（2026-08-23 拷问修复 P1；2026-09-11 caller-sandbox 修正）:
#   0. 常驻 LFL 服务不能继承“谁发起重启”的临时 HOME/TMPDIR。MCP Console 等运维
#      通道可以沙箱自己的 exec，但那不是 LFL 的安全模型。服务恢复当前 Unix 账户的真实
#      HOME 与 macOS 原生 user TMPDIR；LFL 自身的 CatastrophicGuard/EXEC_MODE/approval/
#      EXEC_SANDBOX 继续独立决定工具执行边界。
#   1. DSH_HOME 重定向到镜像区项目内 data/dsh-home —— 否则落到调用方 HOME 下的 ~/.dsh，
#      dsh_task/dsh_session_read 的 session 目录按镜像区 workspace_key 找不到 → 失败。
#      MCP Console 会把 HOME 指向临时沙箱，因此 DSH_HOME 必须显式保留到服务进程，不能
#      在同一函数后续 unset 掉。凭据解析仍可按 DSH 自身契约从 invocation cwd/.env 取得。
#   2. dsh 二进制安装在真实账户 home 的 ~/.local/dsh/bin；服务启动不得依赖调用 shell 的
#      HOME/PATH。用 passwd 数据库解析真实账户 home，只把已存在的 dsh bin 目录加到 PATH；
#      服务 HOME 也明确恢复为该账户 home，不把其它用户目录注入 PATH。
#   3. 清理旧主区 DSH 会话环境残留（DSH_SESSION_JSONL/DSH_SESSION_ID/DSH_SHELL/DSH_WEB_URL）
#      —— 镜像进程若从旧主区 DSH 会话环境启动会携带这些变量，路径解析错指旧主区。
_prep_dsh_env() {
  local account_home="" account_tmp="" dsh_bin_dir=""
  account_home="$("$VENV_PY" -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null || true)"
  if [[ -n "$account_home" ]]; then
    export HOME="$account_home"
    if [[ "$(uname -s)" == "Darwin" ]] && [[ -x /usr/bin/getconf ]]; then
      account_tmp="$(/usr/bin/getconf DARWIN_USER_TEMP_DIR 2>/dev/null || true)"
      if [[ -n "$account_tmp" && -d "$account_tmp" ]]; then
        export TMPDIR="$account_tmp"
      fi
    fi
    dsh_bin_dir="$account_home/.local/dsh/bin"
    if [[ -x "$dsh_bin_dir/dsh" ]]; then
      case ":$PATH:" in
        *":$dsh_bin_dir:"*) ;;
        *) export PATH="$dsh_bin_dir:$PATH" ;;
      esac
    fi
  fi
  export DSH_HOME="$MIRROR_DIR/data/dsh-home"
  mkdir -p "$DSH_HOME"
  unset DSH_SESSION_JSONL DSH_SESSION_ID DSH_SHELL DSH_WEB_URL 2>/dev/null || true

# P1(2026-08-28) 跨区数据锚点污染防御（旧主区实证事故对称防护）: 清空继承锚点键,
# 由本区 .env/默认相对路径接管
# R2(2026-08-29) 补 PYTHONPATH: 旧主区调用侧残留 PYTHONPATH=<旧主区>/src 优先级高于
# venv .pth，会让镜像进程加载旧主区代码（跨区代码污染）；必须清空，模块解析归 venv。
# 补凭证对清理: shell 残留 FEISHU_APP_ID（旧主区 app）无配套 SECRET 时，进程会拼出
# "旧主区 app_id + 镜像 secret"错配对 → 预检 10014 app secret invalid（2026-08-29 实证:
# 旧脚本 source .env 会覆盖残留而掩盖此问题，R2 不 source 后暴露）。清空后由
# python 配置链从 .env/.feishu.env 读配套凭证对。
# 补 DATA_DIR 清理(2026-08-29 第四雷): Settings 消费的是 DATA_DIR 键（≠LFL_DATA_DIR，
# 两个不同的键！），且环境优先压过 .env——启动 shell 残留 DATA_DIR=<旧主区绝对路径>时
# engine 直读旧主区 data → 镜像 web 显示旧主区会话（实证 pid 97159）。清空后由 .env 的
# DATA_DIR=./data（cwd 锚定）接管。
# 补 MCP_SERVERS 清理(2026-09-22 web 30s 假未就绪实证): DSH 会话环境向子 shell
# 注入 MCP_SERVERS=[{"name":"dsh",…dsh_plugin_bridge.mjs}]，进程 env 优先级压过
# .env——2026-09-17 的 .env 注释下线因此失效。服务启动即对已死桥做 15s initialize
# 握手超时（fail-open 警告），并吃掉 web 30s 就绪窗口造成 rc=1 假失败
# （restart-receipt 2026-09-22T21:32）。清空后由本区 .env（无 MCP_SERVERS）接管。
unset LFL_DATA_DIR PYTHONPATH FEISHU_APP_ID FEISHU_APP_SECRET DATA_DIR MCP_SERVERS
}

# 按端口找监听进程（只识别目标端口；不会碰旧主区 8902）。
_port_pid() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}'
}

# 镜像 Web 还可能在收到 SIGTERM 后先释放监听端口、但进程本身继续存活并持有
# <session>.run.lock。只等端口释放会错误地启动第二个 Web，之后所有新请求都被旧
# run owner 判成“另一进程执行”。用镜像 venv 的绝对 argv 精确识别本区 Web，既能
# 找到已经不监听的 stale owner，也不会误杀旧主区不同 venv 的 :8902。
_mirror_web_pids() {
  {
    # Rollout-safe: first C0-B restart must still find the legacy direct-entry process;
    # later restarts must find the canonical runtime.launch process as well.
    pgrep -f "^${VENV_PY} -m llm_loop\.web( |$)" 2>/dev/null || true
    pgrep -f "^${VENV_PY} -m llm_loop\.runtime\.launch web( |$)" 2>/dev/null || true
  } | awk 'NF && !seen[$1]++ {print $1}'
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
  {
    [[ -n "$hb_pid" ]] && echo "$hb_pid"
    # Keep both argv forms during C0-B rollout/rollback. Heartbeat remains authoritative;
    # argv is only the stale/no-heartbeat fallback.
    pgrep -f "^$VENV_PY -m llm_loop\.feishu( |$)" 2>/dev/null || true
    pgrep -f "^$VENV_PY -m llm_loop\.runtime\.launch feishu( |$)" 2>/dev/null || true
  } | awk 'NF && !seen[$1]++ {print $1}'
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

# ── 专门 Learning Plane worker ──
# 无网络监听；runtime manifest 的 pid + argv 是机械身份。Web/Feishu 只入队，
# Reflection consumer 只能由这个独立进程持有。
_learning_pids() {
  local mf="$MIRROR_DIR/data/runtime/runtime_manifest.learning.json"
  local mf_pid=""
  if [[ -f "$mf" ]]; then
    mf_pid="$("$VENV_PY" -c "
import json
try: print(json.load(open('$mf')).get('pid') or '')
except Exception: pass" 2>/dev/null || true)"
  fi
  {
    [[ -n "$mf_pid" ]] && echo "$mf_pid"
    pgrep -f "^$VENV_PY -m llm_loop\.runtime\.launch learning( |$)" 2>/dev/null || true
  } | awk 'NF && !seen[$1]++ {print $1}'
}

_learning_stop() {
  local pids pid survivors
  pids="$(_learning_pids || true)"
  if [[ -z "$pids" ]]; then
    _log "无 Learning Plane worker"
    return 0
  fi
  _log "停止 Learning Plane worker pid(s): $(echo "$pids" | tr '\n' ' ')..."
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
    _log "10s 后 Learning worker 仍存活，强制 kill: $survivors"
    for pid in $survivors; do kill -KILL "$pid" 2>/dev/null || true; done
  fi
  _log "Learning Plane worker 已停止"
}

# ── 回执落盘（修4, 2026-09-09）──
# 实证教训：上轮"watchdog armed, pgid=18559"回执只活在 stdout——载体随宿主死亡，
# 回执无处验证。落盘是唯一可独立核查的载体（设计本身正确，并入脚本）。
# R1 (SPEC-20260922-service-control-restart-fixpack-v1 §6): 回执相对路径契约由
# worker 单源注入（service_control.py:_RESTART_RECEIPT_REL），脚本消费同一值；
# 下方回退默认值必须与 worker 常量字节一致，禁止任何一侧另行猜路径发现。
RECEIPT_REL="${LFL_RESTART_RECEIPT_REL:-data/restart-receipt.json}"
RECEIPT_JSON="$MIRROR_DIR/$RECEIPT_REL"               # 最新一次（覆盖）
RECEIPT_LOG="$MIRROR_DIR/data/restart-receipt.log"     # 历史（追加）
_write_receipt() {
  local action="$1" rc="$2" detail="${3:-}"
  local head head_full web_pid feishu_pid learning_pid receipt_py
  # S2(2026-09-22): dual-root 校验可能正因 .venv 缺失而中止——此时 VENV_PY
  # 不存在，回执写入兜底到系统 python（写入只用 stdlib），保证白名单标记
  # 总能落盘供 worker 消费。
  receipt_py="$VENV_PY"
  [[ -x "$receipt_py" ]] || receipt_py="$(command -v python3 || command -v python || true)"
  if [[ -z "$receipt_py" ]]; then
    _log "⚠️ 回执落盘失败（无可用 python）"
    return 0
  fi
  head="$(git -C "$CODE_ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"
  head_full="$(git -C "$CODE_ROOT" rev-parse HEAD 2>/dev/null || echo '?')"
  web_pid="$(_port_pid "$RESTART_PORT" || true)"
  feishu_pid="$(_feishu_pids 2>/dev/null | head -1 || true)"
  learning_pid="$(_learning_pids 2>/dev/null | head -1 || true)"
  "$receipt_py" - "$RECEIPT_JSON" "$RECEIPT_LOG" "$action" "$rc" "$head" "$head_full" "$detail" "$web_pid" "$feishu_pid" "$learning_pid" <<'PY' 2>/dev/null || { _log "⚠️ 回执落盘失败（不影响服务状态）"; return 0; }
import datetime, json, os, sys
jpath, lpath, action, rc, head, head_full, detail, web_pid, feishu_pid, learning_pid = sys.argv[1:11]
rec = {
    "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "action": action,
    "rc": int(rc),
    "git_head": head,
    "git_head_full": head_full,
    "web_pid": int(web_pid) if web_pid.strip().isdigit() else None,
    "feishu_pid": int(feishu_pid) if feishu_pid.strip().isdigit() else None,
    "learning_pid": int(learning_pid) if learning_pid.strip().isdigit() else None,
    "detail": detail,
    # lifecycle_agency：回执身份绑定（L5）+ 结构化阶段事实（L4）。
    "action_id": os.environ.get("LFL_RESTART_ACTION_ID", ""),
    "stage_fact": os.environ.get("LFL_RESTART_STAGE_FACT", "not_started"),
    # L16/tasks 8.1：单一权威入口——worker 注入 action_id 即权威；直连为非权威
    # 应急通道，显式标注并给出权威入口指引，不产生第二套回执语义。
    "authority": os.environ.get("LFL_RESTART_AUTHORITY", "direct-non-authoritative"),
    "authoritative": os.environ.get("LFL_RESTART_AUTHORITY") == "service_control",
}
if not rec["authoritative"]:
    rec["authority_hint"] = (
        "直连 restart_mirror.sh 为非权威应急通道；模型/自动化请走 "
        "service_control(action=restart|update)"
    )
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
  # C0-B: 正式服务统一经 runtime.launch 解析 canonical runtime snapshot；shell 仅管进程。
  # runtime.launch 在进入 web main 前执行 resolve_effective -> apply_to_environ，确保
  # runtime.toml > .env > stale shell 的同一快照同时供 manifest 与真实 Settings 消费。
  # 清空继承锚点键，让 resolver 依据 runtime_root 决定业务配置权威来源；
  # readiness 必须同时证明后端与 Web V2 路由可用：/auth/status=200 只证明
  # 后端启动，不能证明 gitignored webui/dist 已挂载。/health 在
  # WEB_AUTH_REQUIRE=1 时按设计需要认证。
  # 检查仍用启动前捕获的局部变量（unset 后 $WEB_* 不再绑定，-u 会报错）。
  local check_host="$WEB_HOST" check_port="$WEB_PORT"
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  # 协议 §3 恢复(2026-08-29): 共享 venv 属旧主区（editable .pth 指旧主区 src），
  # 镜像服务必须自带 PYTHONPATH=镜像 src 自卫——不依赖 .pth 指向（.pth 被外力
  # 翻向镜像会反向破坏旧主区；被翻向旧主区则镜像加载错代码。显式注入两边都免疫，
  # 且覆盖 shell 残留的旧主区 PYTHONPATH）。
  # 修3(2026-09-09): 启动改走 _spawn_detached（可移植 setsid+execvp）——nohup+&
  # 不换进程组，宿主 shell 超时 killpg 会被整树波及（execute_command.py:108-109 实证）。
  LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_DEFAULT_WORKSPACE_ROOT="$LFL_DEFAULT_WORKSPACE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" _spawn_detached data/web.log "$VENV_PY" -m llm_loop.runtime.launch web
  local pid=$! auth_code="000" ui_code="000"
  # 就绪预算（2026-10-20 实证）：冷启动含 700 个 legacy evidence sidecar 的
  # quarantine 扫描，实测 29~31s 波动；原 30s 预算在 gen292 部署时以 30.7s
  # 判负 → 控制面自动回滚到旧 release（gen293）。预算须留 legroom，默认 90s；
  # LFL_WEB_READY_TIMEOUT_S 可覆盖（测试/应急），非法或越界回落默认值。
  # 语义是墙钟秒而非迭代次数：单次探测最坏 2×curl --max-time 2 + sleep 1 ≈ 5s，
  # 所以 deadline 是软边界，elapsed 可能略超 budget，日志两者都打以便定位。
  # 判定条件不变（auth/status=200 且 ui/v2 可路由），只放宽等待并记录实测耗时。
  local ready_budget="${LFL_WEB_READY_TIMEOUT_S:-90}"
  if [[ ! "$ready_budget" =~ ^[1-9][0-9]*$ ]] || (( 10#$ready_budget < 5 || 10#$ready_budget > 600 )); then
    ready_budget=90
  fi
  local started_at deadline elapsed
  started_at="$(date +%s)"
  deadline=$(( started_at + ready_budget ))
  while (( $(date +%s) < deadline )); do
    auth_code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "http://$check_host:$check_port/auth/status" 2>/dev/null || true)"
    ui_code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "http://$check_host:$check_port/ui/v2/" 2>/dev/null || true)"
    if [[ "$auth_code" == "200" && "$ui_code" =~ ^[23][0-9][0-9]$ ]]; then
      elapsed=$(( $(date +%s) - started_at ))
      _log "✅ web 就绪: http://$check_host:$check_port/(pid $pid, auth=$auth_code, ui=$ui_code, elapsed=${elapsed}s/${ready_budget}s)"
      return 0
    fi
    sleep 1
  done
  elapsed=$(( $(date +%s) - started_at ))
  if [[ "$auth_code" == "200" ]]; then
    _log "✗ web backend ready but Web V2 unavailable (auth/status=$auth_code, ui/v2=$ui_code, elapsed=${elapsed}s/${ready_budget}s)"
  fi
  _log "✗ web ${ready_budget}s 预算内未就绪（实测 elapsed=${elapsed}s），最近日志:"
  tail -10 data/web.log || true
  return 1
}

_start_feishu() {
  _log "启动飞书桥..."
  _prep_dsh_env
  # C0-B: 同 _start_web——正式配置先经 runtime.launch canonical snapshot；
  # PYTHONPATH=镜像 src 显式注入（协议 §3，同 _start_web 注释）。
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  # 修3(2026-09-09): 同 _start_web——经 _spawn_detached 脱离进程组再 exec。
  LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_DEFAULT_WORKSPACE_ROOT="$LFL_DEFAULT_WORKSPACE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" _spawn_detached data/feishu.log "$VENV_PY" -m llm_loop.runtime.launch feishu
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

_start_learning() {
  _log "启动专门 Learning Plane worker..."
  _prep_dsh_env
  unset WEB_PORT WEB_HOST LFL_DATA_DIR DATA_DIR
  LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_DEFAULT_WORKSPACE_ROOT="$LFL_DEFAULT_WORKSPACE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" _spawn_detached data/learning.log "$VENV_PY" -m llm_loop.runtime.launch learning
  local pid=$!
  local mf="$MIRROR_DIR/data/runtime/runtime_manifest.learning.json"
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then
      _log "✗ Learning worker 提前退出，日志:"
      tail -10 data/learning.log || true
      return 1
    fi
    if [[ -f "$mf" ]] && "$VENV_PY" -c "
import json, sys
try:
    d=json.load(open('$mf'))
except Exception:
    raise SystemExit(1)
sys.exit(0 if d.get('service') == 'learning' and d.get('pid') == $pid else 1)
" 2>/dev/null; then
      _log "✅ Learning Plane worker ready (pid $pid)"
      return 0
    fi
    sleep 1
  done
  _log "✗ Learning worker 30s 未就绪，最近日志:"
  tail -10 data/learning.log || true
  return 1
}


_knowledge_preflight() {
  _log "Knowledge health preflight..."
  if env -u DATA_DIR -u LFL_DATA_DIR -u EXPERIENCES_DIR -u METHODS_DIR -u METHOD_SEED_DIR -u SKILLS_DIR -u DOCS_DIR \
    LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" -m llm_loop.runtime.knowledge_health --preflight --initialize-baseline; then
    _log "✅ Knowledge health preflight PASS"
    return 0
  fi
  # L23/5.2: 保留守卫判定内核；新增模型显式声明出口（不取消守卫本身）。
  if _override_enabled precheck:knowledge_store; then
    _log "⚠️ [OVERRIDE] Knowledge health 已由模型显式声明推进（precheck:knowledge_store），告警放行并留痕"
    return 0
  fi
  _log "✗ Knowledge health preflight FAILED；拒绝停止现有服务，避免在错误/分叉 store 上重启"
  return 1
}

# R2.3(SPEC-20260922-service-control-restart-fixpack-v1): dual-root 共享态部署
# （linked worktree 且 DATA_DIR 在 code root 之外）必须在 .env 显式声明
# EXPERIENCES_DIR/METHODS_DIR canonical 绑定——data_dir 推断正是 gen63 分叉触发器。
# 只读校验（--check-binding 不写任何字节）；mutating 路径中先于 _knowledge_preflight
# 执行，失败复用 knowledge_preflight_failed 标记（R1 白名单内：预检链零物理副作用）。
_knowledge_binding_preflight() {
  _log "Knowledge store binding preflight (R2)..."
  if env -u DATA_DIR -u LFL_DATA_DIR -u EXPERIENCES_DIR -u METHODS_DIR -u METHOD_SEED_DIR -u SKILLS_DIR -u DOCS_DIR \
    LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" "$VENV_PY" -m llm_loop.runtime.knowledge_health --check-binding; then
    _log "✅ Knowledge store binding PASS"
    return 0
  fi
  # L23/5.2: 保留"分叉 store 拒绝静默选赢家"内核；新增模型显式声明出口。
  if _override_enabled precheck:knowledge_binding; then
    _log "⚠️ [OVERRIDE] dual-root store 绑定已由模型显式声明推进（precheck:knowledge_binding），告警放行并留痕"
    return 0
  fi
  _log "✗ dual-root store 绑定缺失/不可写；修复见 RESTART-GUIDE.md §13：主根与 worktree 两份 .env 显式声明 EXPERIENCES_DIR/METHODS_DIR 指向 canonical store，或 override(precheck:knowledge_binding)"
  return 1
}

# EVO-20261009-9d116efa G1：runtime.toml 与目标代码 schema 兼容预检。
# 事故背景：runtime.toml 先落字段、目标代码未注册（2026-10-09 task_budget_canary_config，
# 7fe0170d4 目标重启失败、41 分钟人工回滚）。本预检用【目标 release 自己的 resolver】
# （PYTHONPATH 钉 $CODE_ROOT/src）对 live runtime.toml 做 check-only 严格解析：
# 未知字段/类型不符/密钥违规 ⇒ 中止重启，stage_fact 保持 not_started（零物理副作用，
# R1 白名单标记），旧进程不动。复用目标版本自己的校验代码，不维护第二份字段清单。
_runtime_toml_schema_preflight() {
  [[ -f "$RUNTIME_ROOT/runtime.toml" ]] || {
    _log "ℹ️ runtime.toml 不存在，跳过 schema 预检"
    return 0
  }
  _log "runtime.toml schema preflight（目标代码自校验）..."
  local _out _rc=0
  _out="$(LFL_WORKSPACE_ROOT="$CODE_ROOT" LFL_RUNTIME_ROOT="$RUNTIME_ROOT" PYTHONPATH="$CODE_ROOT/src" \
      "$VENV_PY" -m llm_loop.runtime.resolver --check-toml "$RUNTIME_ROOT/runtime.toml" web feishu learning 2>&1)" || _rc=1
  # fail-closed（实证 2026-10-09）：旧版 resolver 无 --check-toml 入口时静默 exit 0
  # 且零输出（shell 残留 LFL_RESTART_CODE_ROOT 指旧 release 即可触发）——与
  # WEB_PORT 解析同型陷阱。输出缺明确 PASS 标记一律视为校验通道失灵，拒绝停止服务。
  if [[ "$_rc" -eq 0 && "$_out" == *"校验通过"* ]]; then
    _log "✅ runtime.toml schema preflight PASS: $_out"
    return 0
  fi
  if [[ "$_rc" -eq 0 ]]; then
    _log "❌ runtime.toml schema 校验通道失灵（目标 resolver 不支持 --check-toml 或零输出），拒绝停止服务: ${_out:-<empty>}"
  else
    _log "❌ runtime.toml 与目标代码 schema 不兼容（字段未注册/类型违规），拒绝停止服务: $_out"
  fi
  return 1
}


# ── restart 互斥锁（2026-09-24 13:08 双通道并发实证）──
# guard 巡检在权威通道停旧进程的端口空窗 detect_fail → 并发拉起 → 双 web 抢端口
# 一活一死。restart 执行段持有锁，guard 见新鲜锁跳过本轮 pull_up（见 guard_system.sh）。
# 路径锚定 MIRROR_DIR/data（脚本既定事实源）：DATA_DIR 在本脚本是被 unset 的
# 危险键（见上方 543-552 注释），引用它在 set -u 下 unbound 秒退且早于回执
# 写入 → worker 校验读陈旧回执误报 action_id_mismatch，全部 restart 瘫痪
# （2026-09-24 13:4x 实证两连失败）。
_RESTART_LOCK="$MIRROR_DIR/data/runtime/restart-in-progress.lock"
_acquire_restart_lock() {
  mkdir -p "$MIRROR_DIR/data/runtime"
  printf '%s pid=%s argv=%s\n' "$(date -Iseconds)" "$$" "$*" > "$_RESTART_LOCK"
  trap 'rm -f "$_RESTART_LOCK" 2>/dev/null || true' EXIT
}

_status() {
  echo "=== 镜像服务状态 ==="
  local web_pid feishu_pid learning_pid
  web_pid="$(_port_pid "$WEB_PORT" || true)"
  # 修5(2026-09-09): 判定源换 _feishu_pids（心跳 pid 优先 ∪ argv 兜底，uv 改写 argv 场景不再盲）
  feishu_pid="$(_feishu_pids 2>/dev/null | head -1 || true)"
  learning_pid="$(_learning_pids 2>/dev/null | head -1 || true)"
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
  if [[ -n "$learning_pid" ]] && _pid_alive "$learning_pid"; then
    echo "learning: ✅ pid $learning_pid (dedicated Reflection worker)"
  else
    echo "learning: ❌ 未运行"
  fi
  echo "旧主区 web（:8902）: $(curl -sf --max-time 2 http://127.0.0.1:8902/health >/dev/null 2>&1 && echo '✅ 健康' || echo '⚠️ 未运行/不可达')"
}

# ── S1（简化包 2026-09-22）：根检查统一在预检链末端执行 ──
# 位置从文件头部移到 case 之前：本行之前的代码全部只读（cd/resolver/函数定义），
# 根来源中止与 dual-root 校验失败在此统一履行 R1 回执义务（白名单标记 →
# worker 释放屏障），零物理副作用中止不再产生"无回执 keep"死窗。
_code_root_source_check || _root_source_abort LFL_RESTART_CODE_ROOT
_runtime_root_source_check || _root_source_abort LFL_RESTART_RUNTIME_ROOT
_validate_restart_roots || {
  case "$RESTART_ARG1" in
    web|feishu|learning|all)
      mkdir -p "$MIRROR_DIR/data" 2>/dev/null || true
      _write_receipt "$RESTART_ARG1" 2 "dual_root_rejected"
      ;;
  esac
  exit 2
}

if [[ "$RESTART_AUTHORITY" != "service_control" ]]; then
  case "$RESTART_ARG1" in
    web|feishu|learning|all)
      _log "⚠️ [NON-AUTHORITATIVE] 直连重启为非权威应急通道；模型/自动化请走 service_control(action=restart|update)"
      ;;
  esac
fi

case "${1:-web}" in
  preflight) # T0-A3(2026-09-16): 只读 dry-run——根校验+来源判定+webui 产物；
             # 不触任何服务、不验 service_control 绑定（那是 mutating 路径的职责）。
             # R2.3(2026-09-22): 追加 store 绑定校验——dual-root 缺声明在部署预检即 fail。
             # EVO-20261009-9d116efa G1: 追加 runtime.toml schema 兼容性（目标代码自校验）。
             _web_endpoint_preflight || exit 1
             _webui_artifact_preflight || exit 1
             _knowledge_binding_preflight || exit 1
             _runtime_toml_schema_preflight || exit 1
             _log "✅ PREFLIGHT_ONLY 通过（未触碰任何服务）"
             exit 0 ;;
  web)     _webui_artifact_preflight || { _write_receipt web "1" "webui_artifact_preflight_failed"; exit 1; }
           _web_endpoint_preflight || { _write_receipt web "1" "web_endpoint_preflight_failed"; exit 1; }
           _acquire_restart_lock web
           _service_control_preflight web || { _write_receipt web "1" "service_control_binding_failed"; exit 1; }
           _restart_precheck web || { _write_receipt web "1" "active_run_precheck_failed"; exit 1; }
           _knowledge_binding_preflight || { _write_receipt web "1" "knowledge_preflight_failed"; exit 1; }
           _knowledge_preflight || { _write_receipt web "1" "knowledge_preflight_failed"; exit 1; }
           _runtime_toml_schema_preflight || { _write_receipt web "1" "runtime_toml_preflight_failed"; exit 1; }
           _rc=0
           if ! _stop_web "$RESTART_PORT"; then
             _rc=1
             export LFL_RESTART_STAGE_FACT=stop_failed
             _log "web 停止失败，跳过启动（防双进程）"
           else
             export LFL_RESTART_STAGE_FACT=web_stopped
             if _start_web; then
               export LFL_RESTART_STAGE_FACT=started
             else
               _rc=1
             fi
           fi
           _write_receipt web "$_rc" "port=$RESTART_PORT"
           exit "$_rc" ;;
  feishu)  _service_control_preflight feishu || { _write_receipt feishu "1" "service_control_binding_failed"; exit 1; }
           _acquire_restart_lock feishu
           _restart_precheck feishu || { _write_receipt feishu "1" "active_run_precheck_failed"; exit 1; }
           _knowledge_binding_preflight || { _write_receipt feishu "1" "knowledge_preflight_failed"; exit 1; }
           _knowledge_preflight || { _write_receipt feishu "1" "knowledge_preflight_failed"; exit 1; }
           _runtime_toml_schema_preflight || { _write_receipt feishu "1" "runtime_toml_preflight_failed"; exit 1; }
           _rc=0
           if ! _feishu_stop; then
             _rc=1
             export LFL_RESTART_STAGE_FACT=stop_failed
             _log "feishu 停止失败，跳过启动"
           else
             export LFL_RESTART_STAGE_FACT=feishu_stopped
             if _start_feishu; then
               export LFL_RESTART_STAGE_FACT=started
             else
               _rc=1
             fi
           fi
           _write_receipt feishu "$_rc" ""
           exit "$_rc" ;;
  learning) _service_control_preflight learning || { _write_receipt learning "1" "service_control_binding_failed"; exit 1; }
           _knowledge_binding_preflight || { _write_receipt learning "1" "knowledge_preflight_failed"; exit 1; }
           _knowledge_preflight || { _write_receipt learning "1" "knowledge_preflight_failed"; exit 1; }
           _runtime_toml_schema_preflight || { _write_receipt learning "1" "runtime_toml_preflight_failed"; exit 1; }
           _rc=0
           if ! _learning_stop; then
             _rc=1
             export LFL_RESTART_STAGE_FACT=stop_failed
             _log "Learning worker 停止失败，跳过启动"
           else
             export LFL_RESTART_STAGE_FACT=learning_stopped
             if _start_learning; then
               export LFL_RESTART_STAGE_FACT=started
             else
               _rc=1
             fi
           fi
           _write_receipt learning "$_rc" ""
           exit "$_rc" ;;
  all)     _webui_artifact_preflight || { _write_receipt all "1" "webui_artifact_preflight_failed"; exit 1; }
           _web_endpoint_preflight || { _write_receipt all "1" "web_endpoint_preflight_failed"; exit 1; }
           _acquire_restart_lock all
           _service_control_preflight all || { _write_receipt all "1" "service_control_binding_failed"; exit 1; }
           _restart_precheck all || { _write_receipt all "1" "active_run_precheck_failed"; exit 1; }
           _knowledge_binding_preflight || { _write_receipt all "1" "knowledge_preflight_failed"; exit 1; }
           _knowledge_preflight || { _write_receipt all "1" "knowledge_preflight_failed"; exit 1; }
           _runtime_toml_schema_preflight || { _write_receipt all "1" "runtime_toml_preflight_failed"; exit 1; }
           # 修2(2026-09-09): 失败补偿——web 停/启失败不再 && 短路吞掉 feishu 恢复；
           # 各服务按自身停止成败独立决定是否重启（停失败强启=制造双进程，禁止）。
            _rc=0; _web_stopped=0; _feishu_stopped=0; _learning_stopped=0
            _stop_web "$RESTART_PORT" && _web_stopped=1 || _rc=1
            _feishu_stop && _feishu_stopped=1 || _rc=1
            _learning_stop && _learning_stopped=1 || _rc=1
            # stage_fact 取"已执行到的最远阶段"（L4：worker 据此判断零副作用）
            if [[ "$_learning_stopped" -eq 1 ]]; then
              export LFL_RESTART_STAGE_FACT=learning_stopped
            elif [[ "$_feishu_stopped" -eq 1 ]]; then
              export LFL_RESTART_STAGE_FACT=feishu_stopped
            elif [[ "$_web_stopped" -eq 1 ]]; then
              export LFL_RESTART_STAGE_FACT=web_stopped
            else
              # N-1/OQ-11：停止尝试已发生且全部失败 ⇒ 副作用已产生，不得残留 not_started
              export LFL_RESTART_STAGE_FACT=stop_failed
            fi
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
           if [[ "$_learning_stopped" -eq 1 ]]; then
             _start_learning || _rc=1
           else
             _log "Learning worker 停止失败，跳过其启动"
           fi
            if [[ "$_rc" -eq 0 ]]; then
              export LFL_RESTART_STAGE_FACT=started
            fi
            _write_receipt all "$_rc" "web_stopped=$_web_stopped feishu_stopped=$_feishu_stopped learning_stopped=$_learning_stopped"
           exit "$_rc" ;;
  status)  _status ;;
  *)       echo "用法: $0 {web|feishu|learning|all|status}"; exit 1 ;;
esac
