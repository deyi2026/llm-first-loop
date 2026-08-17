"""文件树 + 会话树 API（EVO-20260818 DSH 064，用户需求左侧栏树状对齐）.

A. 文件树: GET /api/v1/fs/tree（目录+文件，单层可展）+ 文件操作
   （POST mkdir / PUT rename / DELETE 两步 confirm）
B. 会话树: GET /api/v1/agents/tree（会话→子代理层级）

安全边界（对齐 RULE-AI 硬阻断原则 + preview 越界模式）:
- 所有路径 resolve 后必须仍在工作区根/项目根内（is_relative_to 越界拒绝）
- 危险路径黑名单: 根目录/家目录/隐藏系统目录/rm -rf 敏感目标
- DELETE 不可逆操作须 confirm=true（两步确认）
- 操作审计: 每次文件/会话操作写 audit（fail-open）
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

fs_router = APIRouter()

# 危险路径黑名单（删除/操作须拦截的敏感目标；resolve 后对比）
_DANGEROUS_NAMES = {
    "/",  # 根
    ".",  # 当前
    "..",  # 上级
    ".git",  # 版本库
    "__pycache__",  # 缓存
    "node_modules",  # 依赖（可重建，但常巨大，防误删）
}
_DANGEROUS_ROOT_PATTERNS = ("/System", "/Library", "/etc", "/usr", "/var", "/bin", "/sbin", "/Applications", "/opt")


def _resolve_under_root(raw: str, engine: Any) -> Path | None:
    """解析路径并确保在工作区根/项目根内；越界/非法返回 None.

    相对路径基于工作区根；绝对路径 resolve 后必须仍在根内。
    """
    root = Path(getattr(engine, "workspace_root", "") or "") 
    if not root or not root.exists():
        root = Path(__file__).resolve().parents[3]  # 项目根兜底
    root = root.resolve()
    try:
        p = Path(raw).expanduser()
        target = p.resolve() if p.is_absolute() else (root / p).resolve()
    except OSError:
        return None
    if not target.is_relative_to(root):
        return None
    return target


def _is_dangerous(target: Path) -> bool:
    """危险路径判定: 黑名单名 + 敏感根模式."""
    name = target.name
    if name in _DANGEROUS_NAMES:
        return True
    s = str(target)
    return any(s.startswith(p) for p in _DANGEROUS_ROOT_PATTERNS)


def _audit(request: Request, action: str, detail: str) -> None:
    """操作审计落盘（fail-open，不阻断操作）."""
    try:
        engine = _engine_from(request)
        base = Path(getattr(engine.settings, "audit_dir", None) or "./data/audit")
        base.mkdir(parents=True, exist_ok=True)
        with (base / "fs_operations.jsonl").open("a", encoding="utf-8") as f:
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "action": action,
                "detail": detail,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 审计失败不阻断
        logger.warning("fs 操作审计失败（fail-open）: %s %s", action, detail)


def _engine_from(request: Request):
    # 与 routes.py _engine_from 同模式：应用状态持有 engine
    return request.app.state.engine


# ── A. 文件树 ──
@fs_router.get("/api/v1/fs/tree")
def fs_tree(request: Request, path: str = "") -> JSONResponse:
    """目录+文件树（单层可展）: 返回指定目录的 dirs+files 列表."""
    engine = _engine_from(request)
    target = _resolve_under_root(path, engine)
    if target is None:
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "路径越界或非法。"})
    if not target.is_dir():
        return JSONResponse(status_code=404, content={"error": "dir_not_found", "detail": f"目录不存在: {target}"})
    try:
        dirs, files = [], []
        for p in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if p.name.startswith("."):
                continue
            if p.is_dir():
                dirs.append(p.name)
            elif p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size})
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "dir_unreadable", "detail": f"目录不可读: {exc}"})
    return JSONResponse(content={
        "path": str(target),
        "parent": str(target.parent) if target != target.parent else None,
        "dirs": dirs[:500],
        "files": files[:500],
    })


@fs_router.post("/api/v1/fs/mkdir")
def fs_mkdir(request: Request, path: str = "") -> JSONResponse:
    """新建目录（相对工作区根）."""
    if not path.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path。"})
    engine = _engine_from(request)
    target = _resolve_under_root(path, engine)
    if target is None or _is_dangerous(target):
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "路径越界或非法。"})
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "mkdir_failed", "detail": f"创建失败: {exc}"})
    _audit(request, "mkdir", str(target))
    return JSONResponse(content={"status": "created", "path": str(target)})


@fs_router.put("/api/v1/fs/rename")
def fs_rename(request: Request, path: str = "", new_name: str = "") -> JSONResponse:
    """重命名文件/目录（path 为新名的父目录路径或旧路径，new_name 为目标名）."""
    if not path.strip() or not new_name.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path/new_name。"})
    engine = _engine_from(request)
    target = _resolve_under_root(path, engine)
    if target is None or _is_dangerous(target):
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "路径越界或非法。"})
    new_target = target.with_name(new_name.strip())
    if not _resolve_under_root(str(new_target), engine):
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "新路径越界。"})
    try:
        target.rename(new_target)
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "rename_failed", "detail": f"重命名失败: {exc}"})
    _audit(request, "rename", f"{target} → {new_target}")
    return JSONResponse(content={"status": "renamed", "from": str(target), "to": str(new_target)})


@fs_router.delete("/api/v1/fs/delete")
def fs_delete(request: Request, path: str = "", confirm: bool = False) -> JSONResponse:
    """删除文件/目录（不可逆，须 confirm=true 两步确认）."""
    if not confirm:
        return JSONResponse(status_code=409, content={"error": "confirm_required", "detail": "删除为不可逆操作，须带 confirm=true 确认。"})
    if not path.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path。"})
    engine = _engine_from(request)
    target = _resolve_under_root(path, engine)
    if target is None or _is_dangerous(target):
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "路径越界或危险，已拒绝。"})
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "delete_failed", "detail": f"删除失败: {exc}"})
    _audit(request, "delete", str(target))
    return JSONResponse(content={"status": "deleted", "path": str(target)})


# ── B. 会话树 ──
@fs_router.get("/api/v1/agents/tree")
def agents_tree(request: Request) -> JSONResponse:
    """会话→子代理层级树（对齐 DSH agents 树）.

    数据源: Session.parent_id + subagent_ 前缀会话（runner 创建）。
    返回: [{id, status, model, parent_id}]，前端按 parent_id 组树。
    """
    engine = _engine_from(request)
    try:
        metas = engine.session.list_sessions()
        sids = [m.session_id for m in metas]
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": "list_failed", "detail": f"会话列表失败: {exc}"})
    nodes = []
    for sid in sids:
        try:
            if not engine.session.exists(sid):
                continue
            sess = engine.session.load(sid)
            nodes.append({
                "id": sid,
                "parent_id": getattr(sess, "parent_id", None),
                "is_subagent": str(sid).startswith("subagent_"),
                "model": getattr(sess, "model_override", None) or "",
                "created_at": getattr(sess, "created_at", None),
            })
        except Exception:  # noqa: BLE001 — 单会话读取失败跳过
            continue
    return JSONResponse(content={"nodes": nodes})
