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


def build_board(
    audit_dir: str | Path,
    *,
    main_head: str = "",
    workspace_root: str = "",
    include_terminal: bool = False,
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

    dep_row, dep_reason = _read_latest_deployment(audit / "deployments")
    if dep_reason:
        degraded.append(dep_reason)
    deployed_sha = str(dep_row.get("target_sha") or "")

    by_status: dict[str, int] = {}
    for row in lanes:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "generated_at": system_local_now().isoformat(),
        "main_head": head,
        "deployment": {
            "deployed_sha": deployed_sha,
            "deployed_at": str(dep_row.get("ts") or ""),
            "deployed_phase": str(dep_row.get("phase") or ""),
            "in_sync": bool(head and deployed_sha and head.startswith(deployed_sha[:12])),
            "source": "audit/deployments",
        },
        "lanes": lanes,
        "summary": {
            "inflight": len(lanes),
            "by_status": by_status,
            "overlaps": _path_overlaps(lanes),
        },
        "degraded": degraded,
    }
