"""Board 只读 HTTP API（DESIGN-20261105 §4.6：main 主线 + 多 lane 并行统一视图）.

对外契约: GET /api/v1/coordination/board 返回
    {"generated_at", "main_head", "deployment": {...}, "lanes": [...],
     "overlaps": [...], "degraded": [...]}

硬约束（与 introspection/lane_board.py 同口径）:
- 零写副作用（A6）：本路由不 mkdir、不 touch、不写审计；数据源缺失一律进 degraded。
- degraded 如实：读不到的数据源逐条透出，不伪造空值（与 coordination_status 同口径）。
- 纯投影：build_board 原生返回里 overlaps 位于 summary.overlaps，本层把它提升为
  顶层 overlaps 以稳定对外契约；数据层（lane_board.py）不改、不重算。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from llm_loop.introspection.lane_board import build_board

logger = logging.getLogger(__name__)
router = APIRouter()
UTF8JSONResponse = JSONResponse


def _engine_from(request: Request) -> Any:
    return request.app.state.engine


def _audit_dir(engine: Any) -> Path:
    """lane 账本目录 = data_dir/audit（与 data/audit/lanes.jsonl 账本口径一致）。"""
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", "./data")
    return Path(str(data_dir)).expanduser() / "audit"


def _workspace_root(engine: Any) -> str:
    # engine.workspace_root 由启动装配（_activate_default_workspace）设定；缺失时兜底 CWD
    # （与 web/__init__.py realtime 工作区口径一致）。probe 失败会如实进 degraded。
    return str(getattr(engine, "workspace_root", "") or "") or str(Path.cwd())


@router.get("/api/v1/coordination/board")
def coordination_board(request: Request) -> JSONResponse:
    """Board 聚合只读视图（部署条带 + 在途 lane + 路径重叠 + degraded）.

    build_board 内部已把各数据源缺失收敛进 degraded（不抛 500）；本层只兜底
    装配级意外（fail-closed：转有界错误 JSON，不向客户端裸抛堆栈）。
    """
    engine = _engine_from(request)
    try:
        board = build_board(
            _audit_dir(engine),
            workspace_root=_workspace_root(engine),
        )
    except Exception as exc:  # noqa: BLE001 — 意外异常必须有界，且如实报告类型
        logger.exception("coordination board build failed")
        return UTF8JSONResponse(
            status_code=500,
            content={
                "error": "coordination_board_failed",
                "detail": "Board 聚合失败：" + type(exc).__name__,
            },
        )
    summary_raw = board.get("summary")
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    overlaps_raw = summary.get("overlaps")
    overlaps = overlaps_raw if isinstance(overlaps_raw, list) else []
    return UTF8JSONResponse(
        content={
            "generated_at": board.get("generated_at", ""),
            "main_head": board.get("main_head", ""),
            "deployment": board.get("deployment", {}),
            "lanes": board.get("lanes", []),
            "overlaps": overlaps,
            "summary": summary,
            "degraded": board.get("degraded", []),
        }
    )
