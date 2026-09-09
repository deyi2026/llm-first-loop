"""Thin authenticated-human file collaboration HTTP adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from llm_loop.workspace.file_effect_query import FileEffectQueryError
from llm_loop.workspace.human_file_ops import HumanFileOperationError

from .schemas import HumanFileEditRequest, HumanFileObserveRequest

file_router = APIRouter()


def _error(status: int, code: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail or code})


def _engine(request: Request) -> Any:
    return request.app.state.engine


def _workspace_scope(engine: Any) -> str:
    return str(Path(getattr(engine, "workspace_root", "") or Path.cwd()).resolve())


def _map_error(exc: HumanFileOperationError) -> JSONResponse:
    code = exc.code
    if code in {"version_conflict", "request_conflict", "session_busy"}:
        return _error(409, code, exc.detail)
    if code in {"session_not_found", "file_not_found"}:
        return _error(404, code, exc.detail)
    if code in {"recording_unavailable", "snapshot_unavailable", "path_lock_unavailable"}:
        return _error(503, code, exc.detail)
    if code == "unsupported_text_encoding":
        return _error(415, code, exc.detail)
    return _error(400, code, exc.detail)


@file_router.post("/api/v1/sessions/{session_id}/files/observe")
def observe_human_file(request: Request, session_id: str, payload: HumanFileObserveRequest):
    engine = _engine(request)
    service = getattr(engine, "human_file_operations", None)
    if service is None:
        return _error(503, "file_collaboration_unavailable")
    try:
        with engine.workspace_snapshot():
            observation = service.observe(
                session_id=session_id,
                workspace_scope=_workspace_scope(engine),
                relative_path=payload.path,
                offset=payload.offset,
                limit=payload.limit,
            )
    except HumanFileOperationError as exc:
        return _map_error(exc)
    return {
        "path": observation.path,
        "snapshot_ref": observation.snapshot_ref,
        "sha256": observation.sha256,
        "size_bytes": observation.size_bytes,
        "observed_at": observation.observed_at,
        "content_range": {
            "start": observation.content_range[0],
            "end_exclusive": observation.content_range[1],
        },
        "content": observation.content,
        "total_lines": observation.total_lines,
        "workspace_path_state": observation.workspace_path_state,
        "file_contract_version": observation.file_contract_version,
    }


@file_router.post("/api/v1/sessions/{session_id}/files/edit")
def edit_human_file(request: Request, session_id: str, payload: HumanFileEditRequest):
    engine = _engine(request)
    service = getattr(engine, "human_file_operations", None)
    if service is None:
        return _error(503, "file_collaboration_unavailable")
    try:
        with engine.workspace_snapshot():
            receipt = service.edit(
                session_id=session_id,
                workspace_scope=_workspace_scope(engine),
                request_id=payload.request_id,
                relative_path=payload.path,
                expected_snapshot_ref=payload.expected_snapshot_ref,
                content=payload.content,
                file_contract_version=payload.file_contract_version,
            )
    except HumanFileOperationError as exc:
        return _map_error(exc)
    return receipt.public_facts()


@file_router.get("/api/v1/sessions/{session_id}/files/operations")
def list_file_operations(request: Request, session_id: str, query: str = "", limit: int = 10):
    engine = _engine(request)
    service = getattr(engine, "file_effect_query", None)
    human = getattr(engine, "human_file_operations", None)
    if service is None or human is None:
        return _error(503, "file_collaboration_unavailable")
    try:
        with engine.workspace_snapshot():
            human.assert_session_available(session_id)
            page = service.query(
                session_id=session_id,
                workspace_scope=_workspace_scope(engine),
                query=query,
                limit=max(1, min(int(limit), 50)),
            )
    except HumanFileOperationError as exc:
        return _map_error(exc)
    except (FileEffectQueryError, TypeError, ValueError) as exc:
        return _error(400, "invalid_query", str(exc))
    return page.public_facts()
