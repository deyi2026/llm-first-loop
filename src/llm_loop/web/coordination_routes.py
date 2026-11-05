"""Board 只读 HTTP API（DESIGN-20261105 §4.6：main 主线 + 多 lane 并行统一视图）.

对外契约: GET /api/v1/coordination/board 返回
    {"generated_at", "main_head", "deployment": {...}, "lanes": [...],
     "overlaps": [...], "degraded": [...]}

硬约束（与 introspection/lane_board.py 同口径）:
- 零写副作用（A6）：本路由不 mkdir、不 touch、不写审计；数据源缺失一律进 degraded。
- degraded 如实：读不到的数据源逐条透出，不伪造空值（与 coordination_status 同口径）。
- 纯投影：build_board 原生返回里 overlaps 位于 summary.overlaps，本层把它提升为
  顶层 overlaps 以稳定对外契约；数据层（lane_board.py）不改、不重算。
- **单闸约定（重要）**：本 router 不自带鉴权，只依赖装配层统一挂载
  `app.include_router(router, dependencies=[Depends(require_api_key)])`
  （见 web/__init__.py）。任何绕过该装配的挂载都会**静默失去鉴权**，
  因此禁止直接 `app.include_router(coordination_routes.router)` 而不带依赖。
  本文件不做 handler 内二次判定，是因为 `auth_required()` 只看 env、不含
  loopback 豁免，会让本机 WebUI 自己的 fetch 被打成 401（已实测回归）。

  **净效果声明（不回避）**：对 loopback 直连，本路由由「401」变为「200」
  ——这是修复 WebUI 取数，不是放宽鉴权；对非 loopback 来源行为不变
  （仍由 `require_api_key` 拦截：未配置凭据 → 503 fail-closed，
  已配置但未认证 → 401）。判定位置由「handler + 装配层两处」收敛为
  「装配层一处」，避免两套语义打架。
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
    # 鉴权只在装配层做一次：web/__init__.py 用
    #   app.include_router(router, dependencies=[Depends(require_api_key)])
    # 统一挂载全部主 router，与 provider_routes 等 sibling 同口径。
    # 此处不能再判 auth_required()：它只看 env、不含 loopback 豁免，
    # 会把本机 WebUI 自己的 fetch 打成 401（实测回归，非安全收紧）。
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
