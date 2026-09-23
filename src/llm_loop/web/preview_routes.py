"""出产物文件预览路由（Web V2 对齐 DSH workspace-files read / documentpreview）.

从 routes.py 抽取的独立路由模块（与 fs_tree/file_routes 同模式）。

契约对齐 DSH workspace-files：
- 文本按 1-based 行分页（offset/limit），页间不重叠、eof 单调收敛——截断后
  必须可继续读取（完整事实源 + 可恢复），不再一次性 20 万字符截断。
- pdf/html/图片走完整字节（base64），超 _PREVIEW_BYTES_MAX 拒绝而非截断
  （不得让派生片段冒充完整文件）。
- 已知无渲染器的二进制容器（音视频/压缩包/office/字体）不读内容，返回
  unsupported_binary 空态（对齐 DSH：never issues a read）。
- 文本严格 UTF-8 + 拒绝 NUL：解码失败如实报 not_text，不用替换字符冒充。

安全边界：拒绝越界路径（resolve 后必须仍在工作区根/项目根内）；仅限普通
文件；分页参数非法（0/负/超上限）拒绝，不静默纠正。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from llm_loop.web.routes import UTF8JSONResponse

logger = logging.getLogger(__name__)

preview_router = APIRouter()

_PREVIEW_ROOT = Path(__file__).resolve().parents[3]  # 项目根（与 _ui_v2_dir 同模式）
_PREVIEW_PAGE_MAX_LINES = 5_000  # 单页行数硬上限（对齐 DSH maxLines）
_PREVIEW_PAGE_DEFAULT_LINES = 2_000  # 默认页大小
_PREVIEW_PAGE_MAX_BYTES = 2 * 1024 * 1024  # 单页字节上限（对齐 DSH maxBytes）
_PREVIEW_BYTES_MAX = 32 * 1024 * 1024  # 完整字节上限 pdf/html/图片（对齐 DSH maxFileBytes）
_PREVIEW_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".bmp": "image/bmp",
}
_PREVIEW_BYTES_MIME = {".pdf": "application/pdf", ".html": "text/html", ".htm": "text/html"}
# 已知二进制容器（无渲染器）：程序不做内容判断，仅按扩展名机械分类
_PREVIEW_UNSUPPORTED_BINARY_EXT = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
    ".pyc", ".class", ".so", ".dylib", ".a", ".o", ".wasm", ".bin", ".exe", ".dll", ".dmg", ".iso",
}


class _PreviewNotTextError(Exception):
    """文本预览源不是可读 UTF-8 文本（含 NUL）。"""


class _PreviewTooLargeError(Exception):
    """单行超出单页字节上限（对齐 DSH：拒绝而非截断）。"""


def _engine_from(request: Request) -> Any:
    # 与 routes.py _engine_from 同模式：应用状态持有 engine
    return request.app.state.engine


def _read_text_page(target: Path, offset: int, limit: int) -> dict[str, Any]:
    """流式读取一个文本页：跳过 offset-1 行，收集至多 limit 行.

    只读到本页末行之后一个字符（大文件每请求只耗一页内存，对齐 DSH page
    cutter）；单行超页字节上限拒绝（不静默丢内容）。
    """
    collected: list[str] = []
    total_bytes = 0
    eof = False
    try:
        with target.open("r", encoding="utf-8", newline="") as f:
            for _ in range(offset - 1):
                if f.readline() == "":
                    eof = True  # offset 越过文件末尾：空页 + eof（对齐 DSH）
                    return {
                        "offset": offset, "lines": 0, "content": "", "eof": True,
                    }
            for _ in range(limit):
                line = f.readline()
                if line == "":
                    eof = True
                    break
                if "\x00" in line:
                    raise _PreviewNotTextError
                line_bytes = len(line.encode("utf-8"))
                if total_bytes + line_bytes > _PREVIEW_PAGE_MAX_BYTES:
                    if not collected:
                        raise _PreviewTooLargeError
                    break  # 页满即止，下一页从下一行继续（不重叠）
                collected.append(line)
                total_bytes += line_bytes
    except UnicodeDecodeError as exc:
        raise _PreviewNotTextError from exc
    return {
        "offset": offset,
        "lines": len(collected),
        "content": "\n".join(line.rstrip("\n") for line in collected),
        "eof": eof,
    }


@preview_router.get("/api/v1/files/preview")
def preview_file(
    request: Request, path: str, offset: int = 1, limit: int = _PREVIEW_PAGE_DEFAULT_LINES
) -> Response:
    """只读文件预览（出产物点击打开；文本分页 + 图片/pdf/html 完整字节 + 目录浏览）.

    安全边界：拒绝绝对路径与越界路径（resolve 后必须仍在项目根内）；
    仅限普通文件；分页参数非法（0/负/超上限）拒绝，不静默纠正。
    """
    if offset < 1 or limit < 1 or limit > _PREVIEW_PAGE_MAX_LINES:
        return UTF8JSONResponse(
            status_code=400,
            content={
                "error": "invalid_range",
                "detail": f"offset/limit 非法：须 1≤offset，1≤limit≤{_PREVIEW_PAGE_MAX_LINES}。",
            },
        )
    if not path:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": "缺少 path。"},
        )
    # 工作区跟随: 预览根 = 当前工作区根（无工作区 → 仓库根兜底）
    engine = _engine_from(request)
    root = Path(getattr(engine, "workspace_root", "") or _PREVIEW_ROOT)
    root_resolved = root.resolve()
    # 相对路径基于工作区根；绝对路径亦接受（resolve 后必须仍在根内，越界拒绝）
    raw = Path(path)
    target = raw.resolve() if raw.is_absolute() else (root_resolved / raw).resolve()
    if not target.is_relative_to(root_resolved):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 裸文件名兜底（正文常引用 `development_methodology.md` 这类无目录前缀的文件名）：
    # 根下直接解析失败时，在工作区常见目录内按 basename 唯一匹配（多命中 → 409 歧义
    # 提示，宁可不猜不错开；防误开原则）。
    if not target.is_file() and not raw.is_absolute() and "/" not in path and "\\" not in path:
        candidates: list[Path] = []
        unsafe_matches = 0
        try:
            for base in ("docs", "src", "tests", "scripts", "skills", "webui"):
                for candidate in (root_resolved / base).rglob(path):
                    if not candidate.is_file():
                        continue
                    resolved = candidate.resolve()
                    if resolved.is_relative_to(root_resolved):
                        candidates.append(resolved)
                    else:
                        unsafe_matches += 1
        except OSError:
            candidates = []
            unsafe_matches = 0
        if len(candidates) == 1:
            target = candidates[0]
        elif len(candidates) > 1:
            return UTF8JSONResponse(
                status_code=409,
                content={
                    "error": "ambiguous_path",
                    "detail": f"文件名 {path} 在工作区内有 {len(candidates)} 处，请用完整路径。",
                },
            )
        elif unsafe_matches:
            return UTF8JSONResponse(
                status_code=400,
                content={"error": "out_of_bounds", "detail": "文件名匹配到项目根外链接，已拒绝。"},
            )
    # 纵深防御：任何 fallback/未来分支最终都必须再次通过解析后根边界。
    if not target.is_relative_to(root_resolved):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 目录 → 单层列表预览（对齐 fs/tree 语义：文档/文件夹/文件皆可点开浏览）
    if target.is_dir():
        try:
            dirs, files = [], []
            for p in sorted(target.iterdir(), key=lambda q: q.name.lower()):
                if p.name.startswith(".") or p.name == "__pycache__":
                    continue
                if p.is_dir():
                    dirs.append(p.name)
                elif p.is_file():
                    files.append({"name": p.name, "size": p.stat().st_size})
        except OSError as exc:
            logger.exception("file preview dir list failed: path=%s", path)
            return UTF8JSONResponse(
                status_code=403,
                content={"error": "dir_unreadable", "detail": f"目录不可读（{type(exc).__name__}）。"},
            )
        # parent 相对根返回（根自身/根外 → "."；前端据此隐藏"返回上级"）
        try:
            rel_parent = str(target.parent.relative_to(root_resolved)) or "."
        except ValueError:
            rel_parent = "."
        return UTF8JSONResponse(
            content={
                "type": "dir",
                "path": path,
                "parent": rel_parent,
                "dirs": dirs[:500],
                "files": files[:500],
            }
        )
    # 图片/pdf/html → 完整字节 base64 预览（≤32MB；超限拒绝，不截断冒充完整）
    import base64

    ext = target.suffix.lower()
    mime = _PREVIEW_IMAGE_MIME.get(ext) or _PREVIEW_BYTES_MIME.get(ext)
    if mime:
        try:
            blob = target.read_bytes()
        except OSError as exc:
            logger.exception("file preview bytes read failed: path=%s", path)
            return UTF8JSONResponse(
                status_code=500,
                content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
            )
        if len(blob) > _PREVIEW_BYTES_MAX:
            return UTF8JSONResponse(
                status_code=413,
                content={
                    "error": "file_too_large",
                    "detail": f"文件 {len(blob)} 字节超完整预览上限 {_PREVIEW_BYTES_MAX} 字节，已拒绝（不截断）。",
                },
            )
        kind = "image" if ext in _PREVIEW_IMAGE_MIME else ("pdf" if ext == ".pdf" else "html")
        return UTF8JSONResponse(
            content={
                "type": kind,
                "path": path,
                "size": len(blob),
                "mime": mime,
                "content_base64": base64.b64encode(blob).decode("ascii"),
            }
        )
    # 已知无渲染器的二进制容器：不读内容，空态告知（程序只做扩展名机械分类）
    if ext in _PREVIEW_UNSUPPORTED_BINARY_EXT:
        return UTF8JSONResponse(
            content={"type": "unsupported_binary", "path": path, "ext": ext}
        )
    if not target.is_file():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "file_not_found", "detail": f"文件不存在: {path}"},
        )
    try:
        size = target.stat().st_size
    except OSError as exc:
        logger.exception("file preview stat failed: path=%s", path)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
        )
    try:
        page = _read_text_page(target, offset, limit)
    except _PreviewNotTextError:
        return UTF8JSONResponse(
            status_code=415,
            content={
                "error": "not_text",
                "detail": "文件不是可预览的 UTF-8 文本（含 NUL 或解码失败）。",
            },
        )
    except _PreviewTooLargeError:
        return UTF8JSONResponse(
            status_code=413,
            content={
                "error": "too_large",
                "detail": f"单行超过单页字节上限 {_PREVIEW_PAGE_MAX_BYTES} 字节，已拒绝（不截断）。",
                "limit": _PREVIEW_PAGE_MAX_BYTES,
            },
        )
    except OSError as exc:
        logger.exception("file preview read failed: path=%s", path)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
        )
    return UTF8JSONResponse(
        content={
            "type": "text",
            "path": path,
            "size": size,
            "offset": page["offset"],
            "lines": page["lines"],
            "content": page["content"],
            "eof": page["eof"],
            "truncated": not page["eof"],  # 兼容旧字段：还有未读内容
        }
    )
