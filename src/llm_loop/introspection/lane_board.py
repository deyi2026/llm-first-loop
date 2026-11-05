"""Board 只读聚合（DESIGN-20261105 §4.6 / 裁决 §11 Q5）.

三条硬约束:
- **零写副作用**（A6）：本模块只读 lanes.jsonl / lane_events.jsonl / deployments/*.jsonl，
  不创建目录、不 touch 文件、不写审计。
- **部署条带必须给出**（裁决 Q5）：`deployed_sha` / `main_head` / `in_sync` 是 Board 最该给的比特。
- **degraded 如实**：读不到的数据源进 `degraded[]`，不伪造空值（与 coordination_status 同口径）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from llm_loop.introspection.lane import LaneStore
from llm_loop.timekeeping import system_local_now


def _probe_git_head(workspace_root: str) -> str:
    if not workspace_root:
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", workspace_root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _read_latest_deployment(dep_dir: Path) -> tuple[dict, str]:
    """返回（最新部署行, degraded 原因）。无 target_sha 的行不算部署事实。"""
    if not dep_dir.is_dir():
        return {}, "deployments_missing"
    best: dict = {}
    best_ts = ""
    for path in sorted(dep_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict) or not row.get("target_sha"):
                        continue
                    ts = str(row.get("ts") or "")
                    if ts >= best_ts:
                        best, best_ts = row, ts
        except OSError:
            continue
    if not best:
        return {}, "deployments_empty"
    return best, ""


def _read_authoritative_receipt(data_root: Path) -> tuple[dict, str]:
    """读 service_control 的 restart-receipt.json —— 当前实际在跑的 sha 的权威事实。

    历史 ``deployments/*.jsonl`` 是人工部署记录，可能长期停在旧 sha；Board 只读它
    会让 ``in_sync`` 变成永久假 mismatch（部署早就切了，条带还指两年前的 commit）。
    restart-receipt 由 service_control 在重启成功后写入，带
    ``authoritative=true`` 与完整 ``git_head_full``，才是"现在跑的是哪个 sha"。
    """
    path = data_root / "restart-receipt.json"
    if not path.is_file():
        return {}, "restart_receipt_missing"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"restart_receipt_unreadable:{type(exc).__name__}"
    if not isinstance(raw, dict):
        return {}, "restart_receipt_bad_shape"
    # 非 authoritative 的回执（例如子代理手工跑脚本留下）不能冒充部署事实。
    if raw.get("authoritative") is not True:
        return {}, "restart_receipt_not_authoritative"
    sha = str(raw.get("git_head_full") or "").strip()
    if not sha:
        return {}, "restart_receipt_no_sha"
    return {
        "target_sha": sha,
        "ts": str(raw.get("ts") or ""),
        "phase": f"service_control:{raw.get('action') or 'restart'}",
        "source": "restart-receipt",
    }, ""


def _path_overlaps(lanes: list[dict]) -> list[dict]:
    """两两路径交叉检测（U5 防重复开发）：同路径或一方是另一方的前缀即视为重叠。"""
    out: list[dict] = []
    for i in range(len(lanes)):
        for j in range(i + 1, len(lanes)):
            a, b = lanes[i], lanes[j]
            b_paths = list(b.get("paths") or [])
            shared: list[str] = []
            for p in a.get("paths") or []:
                pa = str(p).rstrip("/")
                for q in b_paths:
                    qb = str(q).rstrip("/")
                    if pa == qb or pa.startswith(qb + "/") or qb.startswith(pa + "/"):
                        # 两条声明都记下：重叠语义可能由父路径或子路径任一方表达
                        shared.extend([pa, qb])
                        break
            if shared:
                out.append(
                    {
                        "a": a.get("lane_id"),
                        "b": b.get("lane_id"),
                        "branches": [a.get("branch"), b.get("branch")],
                        "shared_paths": sorted(set(shared)),
                    }
                )
    return out


def _read_help_pending(help_dir: Path) -> tuple[dict[str, int], list[dict], str]:
    """读协助收件箱 pending 统计。返回 (counts, degraded_reason).

    刻意不 import introspection.help_inbox：Board 是纯只读投影，直接读目录即可，
    既不与写入侧耦合，也不会因写入侧未就绪而拖垮 Board。单条损坏跳过，不拖垮统计。
    """
    if not help_dir.is_dir():
        return {}, [], "help_inbox_missing"
    pending = 0
    blocking = 0
    items: list[dict] = []
    try:
        for path in help_dir.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            # UnicodeDecodeError 是 ValueError 子类，既不是 OSError 也不是
            # JSONDecodeError：跨会话写入方留下半个 UTF-8 字符时必须跳过，
            # 否则一条坏文件会拖垮整个 board（与 help_inbox._load_message 同口径）。
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("state") or "pending") != "pending":
                continue
            pending += 1
            need = str(row.get("need") or "")
            if need == "block":
                blocking += 1
            # 保留条目供前端在展开态标注「哪条会话在等什么」，只给总数会有数无门。
            items.append(
                {
                    "id": str(row.get("id") or ""),
                    "need": need,
                    "topic": str(row.get("topic") or ""),
                    "from_session": str(row.get("from_session") or ""),
                    "to_session": str(row.get("to_session") or ""),
                    "lane_id": str(row.get("lane_id") or ""),
                    "since": str(row.get("ts") or ""),
                }
            )
    except OSError:
        return {}, [], "help_inbox_unreadable"
    return {"pending_help": pending, "blocking_help": blocking}, items, ""


def _build_channel(
    lanes: list[dict],
    by_status: dict[str, int],
    head: str,
    audit: Path,
    help_session_dir: str | Path | None,
    degraded: list[str],
) -> dict[str, Any]:
    """总协调通道（§4.5 L3）：多少会话在跑 / 多少待协助 / 多少需决策.

    独立成函数而非内联：build_board 已接近函数行数棘轮上限（120），
    新增聚合不应靠放宽基线通过。
    """
    # ---- 总协调通道（§4.5 L3）：一眼看到「多少会话在跑 / 多少待协助 / 多少需决策」。
    # 默认目录 = <data_dir>/interop/session/pending；audit == <data_dir>/audit。
    help_dir = (
        Path(help_session_dir)
        if help_session_dir
        else audit.parent / "interop" / "session" / "pending"
    )
    help_counts, help_items, help_reason = _read_help_pending(help_dir)
    if help_reason:
        degraded.append(help_reason)

    sessions: list[dict] = [
        {
            "session_id": str(row.get("owner_session_id") or ""),
            "lane_id": str(row.get("lane_id") or ""),
            "goal_id": str(row.get("goal_id") or ""),
            "branch": str(row.get("branch") or ""),
            "role": str(row.get("lane_role") or ""),
            "status": str(row.get("status") or ""),
            "last_activity": str(row.get("last_activity") or ""),
        }
        for row in lanes
    ]
    # 需决策 = 正在合并（卡住要人盯）+ 基线已落后的在途 lane（合并前必须重验）
    #        + need=block 的未决协助请求（有人在等答复）。
    stale_count = sum(
        1
        for row in lanes
        if head
        and str(row.get("base_main_sha") or "")
        and str(row.get("base_main_sha") or "") != head
    )

    return {
        "active_lanes": len(lanes),
        "pending_help": help_counts.get("pending_help", 0),
        "blocking_help": help_counts.get("blocking_help", 0),
        "needs_decision": by_status.get("merging", 0)
        + stale_count
        + help_counts.get("blocking_help", 0),
        # 数据源可用性：缺失时上游必须显示「不可用」，不得把 0 当真实计数。
        "help_available": bool(help_counts),
        "lanes_available": not any(
            d.startswith("audit_missing") or d.startswith("lanes_unreadable")
            for d in degraded
        ),
        "sessions": sessions,
        # 展开态需要知道「哪条会话在等什么」：只给计数等于有数无门。
        "help_items": help_items,
        "generated_at": system_local_now().isoformat(),
    }


def build_board(
    audit_dir: str | Path,
    *,
    main_head: str = "",
    workspace_root: str = "",
    include_terminal: bool = False,
    help_session_dir: str | Path | None = None,
) -> dict[str, Any]:
    """聚合在途 lane + 部署条带。纯只读；任何数据源缺失都进 degraded。"""
    audit = Path(audit_dir)
    degraded: list[str] = []

    lanes: list[dict] = []
    if not audit.is_dir():
        # A6: 目录不存在时绝不 mkdir（LaneStore.__init__ 会建目录），直接降级。
        degraded.append("audit_missing")
    else:
        try:
            store = LaneStore(audit)
            lanes = store.list(include_terminal=include_terminal)
        except Exception as exc:  # noqa: BLE001 — 读不到要如实降级，不能让 Board 整体 500
            degraded.append(f"lanes_unreadable:{type(exc).__name__}")

    head = str(main_head or "").strip() or _probe_git_head(workspace_root)
    if not head:
        degraded.append("main_head_unknown")

    # 权威源优先：restart-receipt 记录"当前实际在跑的 sha"；deployments/*.jsonl
    # 是人工历史记录，可能长期停在旧 sha。权威源缺失才回退，且回退原因如实进 degraded。
    dep_row, dep_reason = _read_authoritative_receipt(audit.parent)
    if dep_reason:
        degraded.append(dep_reason)
        dep_row, hist_reason = _read_latest_deployment(audit / "deployments")
        if hist_reason:
            degraded.append(hist_reason)
    deployed_sha = str(dep_row.get("target_sha") or "")

    by_status: dict[str, int] = {}
    for row in lanes:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    channel = _build_channel(lanes, by_status, head, audit, help_session_dir, degraded)

    # in_sync 必须精确：部署记录可能是短 sha 或残缺 sha，startswith 会把
    # "head 只是以它开头"误判成"已部署的就是当前 head"（假绿）。三态显式化，
    # 只有 exact 才算同步，prefix_only 单独暴露给 Board 显示。
    if head and deployed_sha:
        if head == deployed_sha:
            sync_state = "exact"
        elif len(deployed_sha) >= 12 and head.startswith(deployed_sha):
            sync_state = "prefix_only"
        else:
            sync_state = "mismatch"
    else:
        sync_state = "unknown"

    return {
        "generated_at": system_local_now().isoformat(),
        "main_head": head,
        "deployment": {
            "deployed_sha": deployed_sha,
            "deployed_at": str(dep_row.get("ts") or ""),
            "deployed_phase": str(dep_row.get("phase") or ""),
            "in_sync": sync_state == "exact",
            "sync_state": sync_state,
            "source": str(dep_row.get("source") or "audit/deployments"),
        },
        "channel": channel,
        "lanes": lanes,
        "summary": {
            "inflight": len(lanes),
            "by_status": by_status,
            "overlaps": _path_overlaps(lanes),
        },
        "degraded": degraded,
    }
