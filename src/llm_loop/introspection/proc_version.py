"""进程代码版本一致性检测与变更协调（EVO-20260811-f94e5306）.

① record_process_start: 进程启动时记录启动时间 + git HEAD（web/cli/feishu 入口调用）。
② get_process_versions: 读取记录 + 当前 git HEAD 对照，旧代码进程标注"建议重启"。
③ record_change_log: 修改类工具调用通告（多会话协调，可经 search_records 检索）。
全部 fail-open（记录失败不阻断业务）。
"""

import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _audit_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "audit"


def git_head() -> str:
    """当前代码 git HEAD（短 hash；非 git 仓库/不可用返回 no-git，如实标注）."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
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
            ["git", "status", "--short"],
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
            ["git", "status", "--short"],
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
            "ts": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "service": service,
            "git_head": git_head(),
            "workspace_dirty": workspace_dirty(),
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
    for svc, r in latest_by_service.items():
        head = r.get("git_head", "")
        start_dirty = bool(r.get("workspace_dirty", False))
        same_head = head == current
        if not same_head:
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
                "note": note,
            }
        )
    services.sort(key=lambda s: s["started_at"], reverse=True)
    return {
        "current_git_head": current,
        "current_workspace_dirty": current_dirty,
        "services": services,
        "note": "进程启动时记录 git HEAD；启动早于代码变更的进程标注建议重启（EVO-20260811-f94e5306）；EVO-20260811-a30732d9 增加工作区 dirty 检测",
    }


def check_self_stale() -> str:
    """本进程代码时效性轻量检查（EVO-20260815-69ac0bd0 S1 问题机制化）.

    检测逻辑复用（git_head/workspace_dirty），结果提升为"主动提示"而非
    "被动可查"（埋 architecture_status 深层字段、AI 不主动查看不到的治理）。
    EVO-20260817-cef296f8: 增加服务级对照——工作区干净但存在"启动 HEAD 落后于
    当前 HEAD"的进程（已 commit 未重启）同样提示（本次 feishu 事故缺口：
    修复提交后 web 重启但 feishu 未重启，dirty 检测不触发、对照仅被动可查）。

    Returns:
        "" = 一致（head 一致且工作区干净且无旧代码服务）；否则一句话提示（含 commit+重启建议）。
        提示为只读信息，AI 自主决定是否处理；检查 fail-open，异常返回 "" 不阻断。
    """
    try:
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
            "ts": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "tool": tool_name,
            "session_id": session_id,
            "detail": str(detail)[:300],
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 记录失败不阻断工具执行
