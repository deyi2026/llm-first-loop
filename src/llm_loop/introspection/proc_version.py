"""进程代码版本一致性检测与变更协调（EVO-20260811-f94e5306）.

① record_process_start: 进程启动时记录启动时间 + git HEAD（web/cli/feishu 入口调用）。
② get_process_versions: 读取记录 + 当前 git HEAD 对照，旧代码进程标注"建议重启"。
③ record_change_log: 修改类工具调用通告（多会话协调，可经 search_records 检索）。
④ guard_code_drift: 守卫模块（命令闸/工具安全层）加载版本 vs 源码树——回答
   "我刚改的守卫判定，本进程真的在跑吗"。HEAD 对照看不见未提交改动，
   守卫层恰恰是改了就必须重启才可信的一层（2026-11-01 事故缺口）。
全部 fail-open（记录失败不阻断业务）。
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from ..core import guard_code as _guard_code
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)


def _source_workspace() -> Path | None:
    """Explicit source workspace for dual-root runtime identity, else legacy CWD."""
    raw = (os.environ.get("LFL_WORKSPACE_ROOT") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


# ── 守卫代码时效（守卫层专用，见模块 docstring ④）─────────────────────────
# 原语放 core（runtime 的 manifest/service_control 也要用同一份判据，若放这里会
# 让 runtime 新增跨 plane 反向依赖，Kernel v1 import ratchet 实测拦截）；本模块
# 负责"快照 + 判定 + 提示"这层，命名沿用历史 API（测试按此契约）。
GUARD_MODULES = _guard_code.GUARD_MODULES
guard_code_fingerprint = _guard_code.guard_code_fingerprint
_package_root = _guard_code.package_root
_module_name = _guard_code.module_name
_repo_root_from = _guard_code.repo_root_from

# import 时刻的快照 = 本进程随后会执行的那份守卫代码（内存里的，不随磁盘变动）。
# 边界：生产入口在启动时即 import 本模块，故快照≈启动时刻；若同进程内先改守卫
# 文件、之后才首次 import 本模块，该窗口会假阴性——守卫改动一律以重启后为可信。
_GUARD_SNAPSHOT: dict[str, str] = guard_code_fingerprint()


def _source_root() -> Path:
    """对照基准：可编辑源码树的 llm_loop 包根.

    顺序：① core 原语按加载路径反推（``<repo>/.releases/<sha>/src/llm_loop`` →
    ``<repo>/src/llm_loop``，release 副本自带的 .git 会骗过 git 探测，故用路径
    结构）；② 显式 LFL_WORKSPACE_ROOT；③ 本进程加载的包根。取第一个真的含守卫
    模块的候选，都不含则返回包根（由调用方判为不可判定）。
    """
    root = _guard_code.repo_source_root()
    if root is not None:
        return root
    ws = _source_workspace()
    if ws is not None:
        for cand in (ws / "src" / "llm_loop", ws):
            if _guard_code.is_llm_loop_package(cand):
                return cand
    return _package_root()


def guard_source_root() -> Path | None:
    """对照用的源码包根；不可判定（如运行在无关工作区里）→ None.

    宁可"不可判定"也不误报：把无关工作区当源码树会让全部守卫模块记 missing，
    于是恒判 stale——那会把提示本身变成噪音（比没有提示更糟）。
    """
    root = _source_root()
    return root if _guard_code.is_llm_loop_package(root) else None

def guard_code_drift() -> dict:
    """本进程加载的守卫代码 vs 源码树当前守卫代码.

    ``stale=True``: 源码树守卫代码已变、本进程仍执行启动时版本 → 新判定/新放行
    逻辑要重启才生效。``changed_unloaded``: 磁盘已变但该模块本进程尚未 import
    （首次 import 会读到新代码），只作信息项、不计入 stale——不把"将读到新代码"
    误报成"在跑旧代码"。检测异常 / 源码树不可判定 fail-open，字段如实标注。
    """
    try:
        root = guard_source_root()
        if root is None:
            return {
                "stale": False,
                "changed": [],
                "changed_loaded": [],
                "changed_unloaded": [],
                "undetermined": "source_root_has_no_llm_loop_package",
            }
        current = guard_code_fingerprint(root)
        baseline = dict(_GUARD_SNAPSHOT)
        changed = [r for r in GUARD_MODULES if baseline.get(r) != current.get(r)]
        loaded = [r for r in changed if _module_name(r) in sys.modules]
        return {
            "stale": bool(loaded),
            "changed": changed,
            "changed_loaded": loaded,
            "changed_unloaded": [r for r in changed if r not in loaded],
            "source_root": str(root),
        }
    except Exception as exc:  # noqa: BLE001 — fail-open，不阻断业务
        return {
            "stale": False,
            "changed": [],
            "changed_loaded": [],
            "changed_unloaded": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def guard_code_note() -> str:
    """守卫代码时效一句话提示；一致或不可判定返回 ""."""
    drift = guard_code_drift()
    if not drift.get("stale"):
        return ""
    mods = "、".join(drift.get("changed_loaded") or [])
    return (
        f"[守卫代码时效提示] 源码树的守卫模块已变更（{mods}），本进程仍执行启动时"
        "加载的版本——新判定/新放行逻辑重启后才生效，在此之前据其声明"
        "\"修复已生效\"会误判。建议 commit 后 service_control publish/restart "
        "对应服务。是否处理由你决定（只读提示，不阻断）。"
    )


def _git_command(*args: str) -> list[str]:
    cmd = ["git"]
    source = _source_workspace()
    if source is not None:
        cmd.extend(["-C", str(source)])
    cmd.extend(args)
    return cmd


def _audit_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "audit"


def git_head() -> str:
    """当前代码 git HEAD（短 hash；非 git 仓库/不可用返回 no-git，如实标注）."""
    try:
        r = subprocess.run(
            _git_command("rev-parse", "--short", "HEAD"),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() if r.returncode == 0 else "no-git"
    except Exception:  # noqa: BLE001 — 非 git/异常如实降级
        return "no-git"


def workspace_dirty() -> bool:
    """工作区是否含未提交改动（git status --short 非空=True；异常如实降级 False，不阻断）."""
    try:
        r = subprocess.run(
            _git_command("status", "--short"),
            capture_output=True,
            text=True,
            timeout=3,
        )
        return bool(r.stdout.strip()) if r.returncode == 0 else False
    except Exception:  # noqa: BLE001 — 非 git/异常如实降级
        return False


def workspace_diff_summary(max_chars: int = 120) -> str:
    """工作区未提交改动摘要（git status --short 前 N 字符；无改动/异常返回空串）."""
    try:
        r = subprocess.run(
            _git_command("status", "--short"),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode != 0:
            return ""
        return r.stdout.strip().replace("\n", "; ")[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def record_process_start(service: str) -> None:
    """记录进程启动（启动时间 + PID + git HEAD）到 proc_versions.jsonl（fail-open）."""
    try:
        path = _audit_dir() / "proc_versions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": system_local_now().isoformat(),
            "pid": os.getpid(),
            "service": service,
            "git_head": git_head(),
            "workspace_dirty": workspace_dirty(),
            # 守卫模块指纹：进程启动时加载的那份（后续对照源码树即可知是否需要重启）
            "guard_code": dict(_GUARD_SNAPSHOT),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 记录失败不阻断启动


def get_process_versions(limit: int = 30) -> dict:
    """各服务进程版本状态：最新记录 + 当前 git HEAD 对照，旧代码标注建议重启.

    Returns:
        {"current_git_head": str, "services": [{"service", "pid", "started_at",
         "git_head", "code_current", "note"}], "note": str}
    """
    current = git_head()
    path = _audit_dir() / "proc_versions.jsonl"
    records: list[dict] = []
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError as exc:  # fail-open：读进程版本文件失败视为空
            logger.debug("读进程版本文件失败（fail-open）: %s", exc)
    records = records[-limit:]
    # 每服务取最新一条（旧记录保留可查但状态只看最新）
    latest_by_service: dict[str, dict] = {}
    for r in records:
        latest_by_service[r.get("service", "?")] = r
    services = []
    current_dirty = workspace_dirty()
    guard_root = guard_source_root()
    guard_now = guard_code_fingerprint(guard_root) if guard_root is not None else None
    for svc, r in latest_by_service.items():
        head = r.get("git_head", "")
        start_dirty = bool(r.get("workspace_dirty", False))
        same_head = head == current
        # 守卫代码对照（旧记录无 guard_code、或源码树不可判定 → None，未知不伪造"一致"）
        rec_guard = r.get("guard_code")
        if guard_now is not None and isinstance(rec_guard, dict) and rec_guard:
            guard_changed = [
                m for m in GUARD_MODULES if rec_guard.get(m) != guard_now.get(m)
            ]
            guard_current: bool | None = not guard_changed
        else:
            guard_changed = []
            guard_current = None
        if guard_current is False:
            # 比 HEAD 不等更具体：守卫层改了没重启 → 判定/放行仍是旧逻辑
            note = (
                "守卫模块与源码树不一致（命令闸/安全层仍是启动时版本，"
                "重启后才生效）"
            )
        elif not same_head:
            note = "启动时代码与当前 HEAD 不一致（旧代码，建议重启）"
        elif start_dirty or current_dirty:
            note = "工作区含未提交改动（进程加载代码可能与 HEAD 不一致），建议及时 commit 并重启"
        else:
            note = ""
        services.append(
            {
                "service": svc,
                "pid": r.get("pid"),
                "started_at": r.get("ts", ""),
                "git_head": head,
                "workspace_dirty": start_dirty,
                "code_current": same_head,
                "guard_code_current": guard_current,
                "guard_code_changed": guard_changed,
                "note": note,
            }
        )
    services.sort(key=lambda s: s["started_at"], reverse=True)
    drift = guard_code_drift()
    return {
        "current_git_head": current,
        "current_workspace_dirty": current_dirty,
        "guard_code_now": guard_now,
        "guard_code_self": {
            "stale": drift.get("stale"),
            "changed_loaded": drift.get("changed_loaded", []),
            "changed_unloaded": drift.get("changed_unloaded", []),
            **({"error": drift["error"]} if drift.get("error") else {}),
        },
        "services": services,
        "note": "进程启动时记录 git HEAD；启动早于代码变更的进程标注建议重启（EVO-20260811-f94e5306）；EVO-20260811-a30732d9 增加工作区 dirty 检测；守卫模块指纹对照见 guard_code_* （旧记录无该字段 → guard_code_current=null 表示未知）",
    }


def check_self_stale() -> str:
    """本进程代码时效性轻量检查（EVO-20260815-69ac0bd0 S1 问题机制化）.

    检测逻辑复用（git_head/workspace_dirty），结果提升为"主动提示"而非
    "被动可查"（埋 architecture_status 深层字段、AI 不主动查看不到的治理）。
    EVO-20260817-cef296f8: 增加服务级对照——工作区干净但存在"启动 HEAD 落后于
    当前 HEAD"的进程（已 commit 未重启）同样提示（本次 feishu 事故缺口：
    修复提交后 web 重启但 feishu 未重启，dirty 检测不触发、对照仅被动可查）。

    ``check_stale_services`` 之外增加守卫层专用对照：工作区 dirty 与 HEAD 不一致
    都只说明"代码可能变了"，唯独守卫模块（命令闸/安全层）变了的后果是**安全判定
    被放松而不自知**，因此单列一条提示（2026-11-01：命令闸修复已提交但本进程仍跑
    旧字节码，差点据旧行为声明"修复已生效"）。

    Returns:
        "" = 一致（head 一致且工作区干净且无旧代码服务）；否则一句话提示（含 commit+重启建议）。
        提示为只读信息，AI 自主决定是否处理；检查 fail-open，异常返回 "" 不阻断。
    """
    try:
        guard_note = guard_code_note()
        if guard_note:
            return guard_note
        head = git_head()
        if head == "no-git":
            return ""
        dirty = workspace_dirty()
        if dirty:
            return (
                f"[进程代码时效提示] 工作区含未提交改动（HEAD {head}）——本进程加载的代码"
                "可能与磁盘不一致；如涉及刚改动的模块，判断结果可能基于旧逻辑。"
                "建议及时 git commit；长驻进程（feishu/web 网关等）需重启后新代码生效。"
                "是否处理由你决定（提示只读，不阻断）。"
            )
        # 工作区干净但存在旧代码服务（启动 HEAD 落后于当前 HEAD）
        stale = check_stale_services()
        if stale:
            return stale
    except Exception:  # noqa: BLE001 — 检查异常如实降级，不阻断循环
        return ""
    return ""


def check_stale_services(limit: int = 10) -> str:
    """服务级旧代码检测（EVO-20260817-cef296f8 L1）.

    对照 proc_versions.jsonl 中每服务最新启动记录与当前 git HEAD，
    存在 code_current=False（启动 HEAD ≠ 当前 HEAD）的进程 → 返回主动提示
    （含服务/PID/启动时 HEAD/当前 HEAD）；全部一致返回 ""。
    fail-open：读记录/解析异常返回 "" 不阻断。
    """
    try:
        info = get_process_versions(limit=30)
        stale_services = [
            s
            for s in info.get("services", [])
            if not s.get("code_current", True) and s.get("service") != "cli"
        ]
        if not stale_services:
            return ""
        head = info.get("current_git_head", "?")
        detail = "; ".join(
            f"{s['service']}(pid={s['pid']}, 启动 HEAD {s.get('git_head', '?')})"
            for s in stale_services[:3]
        )
        extra = f" 共 {len(stale_services)} 个" if len(stale_services) > 3 else ""
        return (
            f"[进程代码时效提示] 存在旧代码进程：{detail}{extra}——当前 HEAD {head}，"
            "这些进程启动早于最近提交，仍在运行旧代码（缓存去重等修复未生效，"
            "可能持续产生全价缓存 MISS/旧行为）。建议任务间隙重启对应服务"
            "（scripts/restart_system.sh <svc> restart）。是否处理由你决定（提示只读）。"
        )
    except Exception:  # noqa: BLE001
        return ""


def record_change_log(tool_name: str, detail: str, session_id: str = "") -> None:
    """变更通告：修改类工具调用记录（多会话协调，可检索，fail-open）.

    detail 截断 300 字符防膨胀；记录谁（pid/ts）何时执行了什么修改动作。
    """
    try:
        path = _audit_dir() / "change_log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": system_local_now().isoformat(),
            "pid": os.getpid(),
            "tool": tool_name,
            "session_id": session_id,
            "detail": str(detail)[:300],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 记录失败不阻断工具执行
