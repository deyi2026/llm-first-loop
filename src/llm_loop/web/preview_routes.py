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

安全边界（安全建议书 2026-10-25 P1-3 / S2-1 收紧后）：
- 预览根 = 当前工作区根；workspace_root 为空/不可解析/目录不存在 → 503
  workspace_unconfigured，绝不回退项目根（旧回退曾把仓库 .env、data/ 会话
  整面暴露给预览端点，S2-1 实测 200/808B）。
- 拒绝越界路径（resolve 后必须仍在工作区根内）；仅限普通文件；分页参数
  非法（0/负/超上限）拒绝，不静默纠正。
- 敏感文件拒绝（共享 security_guard.sensitive_path_reason，不另立名单）：
  命中 → 403 sensitive_file_blocked，不读取内容、不返回大小/预览。
- 版本库元数据与运行时状态目录拒绝（R2-6）：路径组件命中 .git/
  .lfs_checkpoints（任意段，大小写不敏感）或顶层 data（第 1 段）→ 403
  sensitive_file_blocked（reason dir:<名>）；按组件精确比较，不影响
  data_analysis.py / src/data_loader.py 这类文件名。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from llm_loop import security_guard
from llm_loop.web.routes import UTF8JSONResponse

logger = logging.getLogger(__name__)

preview_router = APIRouter()

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
# readRelated 可打包范围（对齐 DSH + CSS url() 资产扩展）：
# - 文本类：直接声明的经典 .js 与 .css（须合法 UTF-8）；
# - 二进制类：CSS url()/@import 引用的图片与字体（原样字节，不做 UTF-8 校验）。
# 模块导入、动态 fetch 不走 Host 文件读取。机械扩展名门，无内容判断。
_RELATED_MIME = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".bmp": "image/bmp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".otf": "font/otf", ".eot": "application/vnd.ms-fontobject",
}
_RELATED_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}
_RELATED_MAX_BYTES = 4 * 1024 * 1024  # 单资产上限（对齐 DSH 4 MiB per asset）
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


def _workspace_root_or_none(engine: Any) -> Path | None:
    """解析当前工作区根（P1-3：未配置即拒绝，绝不回退项目根）.

    workspace_root 为空 / 不可解析 / 目录不存在 → None；调用方必须以
    503 workspace_unconfigured 拒绝（旧实现静默回退仓库根，把 .env、
    data/ 会话整面暴露给预览端点——建议书 S2-1 实测 200/808B）。
    """
    raw = getattr(engine, "workspace_root", "") or ""
    text = str(raw).strip()
    if not text:
        return None
    try:
        root = Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return root if root.is_dir() else None


def _workspace_unconfigured_response() -> Response:
    return UTF8JSONResponse(
        status_code=503,
        content={
            "error": "workspace_unconfigured",
            "detail": "工作区未配置或不可用；预览面不回退项目根，已拒绝。",
        },
    )


def _sensitive_blocked_response(reason: str) -> Response:
    return UTF8JSONResponse(
        status_code=403,
        content={"error": "sensitive_file_blocked", "reason": reason},
    )


# R2-6（红队第二轮 #6 + 父代理补充）：预览面拒绝版本库元数据与运行时状态目录。
# - .git / .lfs_checkpoints：工作区相对路径**任意段**命中即拒（大小写不敏感）；
# - data：仅**第 1 段**命中即拒（会话 JSON、escalation 日志、审计等运行时状态）。
# 判定按路径组件精确比较（先 lower 再整名等值）——data_analysis.py /
# src/data_loader.py 这类文件名不受影响（不做子串匹配）。
_PREVIEW_BLOCKED_ANY_SEGMENT = frozenset({".git", ".lfs_checkpoints"})
_PREVIEW_BLOCKED_TOP_SEGMENT = frozenset({"data"})

# N11（2026-10-25 第四轮红队）：模板后缀内容复核的读取上限（强密钥特征
# 都在文件头部；超大模板也只扫前 256KiB，防内容扫描被大文件放大）。
_TEMPLATE_SECRET_SCAN_MAX_BYTES = 256 * 1024


def _template_content_has_strong_secret(target: Path) -> bool:
    """模板后缀文件的内容强密钥复核（复用 security_guard.has_strong_secret）.

    名字豁免（.example 等）只覆盖"占位符模板"预期；`.env` 内容被 cp/改名
    洗到模板名下时，内容层必须复核。读取失败按未命中处理（后续正常读取
    路径会如实报错，不在此处吞掉 IO 异常语义）。
    """
    try:
        if not target.is_file():
            return False
        with target.open("rb") as f:
            blob = f.read(_TEMPLATE_SECRET_SCAN_MAX_BYTES)
    except OSError:
        return False
    return security_guard.has_strong_secret(blob.decode("utf-8", "replace"))


def _runtime_state_blocked_reason(target: Path, root_resolved: Path) -> str | None:
    """预览目标命中版本库/运行时状态目录 → 403 原因（``dir:<小写规范名>``）.

    调用点均已先通过"resolve 后仍在工作区根内"的越界检查，relative_to 不会
    失败；防御分支返回 None 由外层越界检查兜底（本函数不另立根语义）。
    """
    try:
        parts = target.relative_to(root_resolved).parts
    except ValueError:
        return None
    lowered = [str(p).lower() for p in parts]
    for name in lowered:
        if name in _PREVIEW_BLOCKED_ANY_SEGMENT:
            return f"dir:{name}"
    if lowered and lowered[0] in _PREVIEW_BLOCKED_TOP_SEGMENT:
        return f"dir:{lowered[0]}"
    return None


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

    安全边界：拒绝绝对路径与越界路径（resolve 后必须仍在工作区根内；
    工作区未配置 → 503 不回退项目根）；敏感文件名命中 → 403 不读内容；
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
    # 工作区跟随（P1-3 收紧）：预览根 = 当前工作区根；未配置/不可用 → 503，
    # 绝不回退仓库根。
    engine = _engine_from(request)
    root_resolved = _workspace_root_or_none(engine)
    if root_resolved is None:
        return _workspace_unconfigured_response()
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
    # 敏感文件拒绝（P1-3，共享 security_guard 原语）：判定只看路径形态，
    # 先于存在性检查（避免泄露敏感文件存在性）；命中即 403，不读内容、
    # 不返回大小/预览（敏感目录同样不列清单）。
    sensitive_reason = security_guard.sensitive_path_reason(target)
    if sensitive_reason is not None:
        return _sensitive_blocked_response(sensitive_reason)
    # N11 / M9（2026-10-25 第五轮红队）：内容层强密钥复核必须覆盖**所有文本预览**，
    # 而不是只看模板后缀名。`.env` 被复制/改名为 a.md、notes.txt 等普通名时，
    # 名字层不会命中敏感名单；若只对 *.example 复核，就等于把"复制即洗白"留在原地。
    # 命中即 403（不返回内容、不泄露大小）；大文件/二进制按 helper 的读取上限处理。
    if target.is_file() and _template_content_has_strong_secret(target):
        return _sensitive_blocked_response("content:strong-secret")
    # R2-6：版本库元数据（.git/.lfs_checkpoints，任意段）与顶层运行时状态目录
    # （data，第 1 段）同样 403——先于目录列举/存在性检查，不泄露清单。
    runtime_reason = _runtime_state_blocked_reason(target, root_resolved)
    if runtime_reason is not None:
        return _sensitive_blocked_response(runtime_reason)
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
            st = target.stat()
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
                "mtime_ns": st.st_mtime_ns,
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
        st = target.stat()
        size = st.st_size
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
            "mtime_ns": st.st_mtime_ns,
            "offset": page["offset"],
            "lines": page["lines"],
            "content": page["content"],
            "eof": page["eof"],
            "truncated": not page["eof"],  # 兼容旧字段：还有未读内容
        }
    )


def _resolve_in_root(raw: str, root_resolved: Path) -> Path | None:
    """按 preview 同规则解析路径：相对基于工作区根，绝对 resolve 后须在根内.

    调用方先用 _workspace_root_or_none 取根（None → 503，不回退项目根）；
    本函数只做纯解析与越界判定，不另立根语义。
    """
    try:
        p = Path(raw).expanduser()
        target = p.resolve() if p.is_absolute() else (root_resolved / p).resolve()
    except OSError:
        return None
    if not target.is_relative_to(root_resolved):
        return None
    return target


@preview_router.get("/api/v1/files/related")
def related_file(request: Request, base: str, path: str) -> Response:
    """readRelated：解析 base 文件目录下的相对依赖（HTML 预览打包 .js/.css）.

    对齐 DSH workspace-files.readRelated 的安全面：target 由 Host 从 base 的
    目录解析（含 ../），resolve 后必须仍在根内；仅 .js/.css；单资产 4MiB
    上限拒绝不截断；内容须为合法 UTF-8（内联前置校验，失败即失败不部分发布）。
    工作区未配置 → 503；base 或依赖命中敏感名单 → 403（P1-3）。
    """
    import base64

    if not base or not path:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": "缺少 base/path。"},
        )
    engine = _engine_from(request)
    root_resolved = _workspace_root_or_none(engine)
    if root_resolved is None:
        return _workspace_unconfigured_response()
    base_target = _resolve_in_root(base, root_resolved)
    if base_target is None:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "base 路径越出项目根，已拒绝。"},
        )
    # base 本身命中敏感名（如以 .env 为打包基点）→ 403，不读内容。
    base_sensitive = security_guard.sensitive_path_reason(base_target)
    if base_sensitive is not None:
        return _sensitive_blocked_response(base_sensitive)
    # R2-6：base 命中 .git/.lfs_checkpoints（任意段）或顶层 data → 403。
    base_runtime = _runtime_state_blocked_reason(base_target, root_resolved)
    if base_runtime is not None:
        return _sensitive_blocked_response(base_runtime)
    if not base_target.is_file():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "file_not_found", "detail": f"base 文件不存在: {base}"},
        )
    try:
        target = (base_target.parent / path).resolve()
    except OSError:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "依赖路径非法。"},
        )
    if not target.is_relative_to(root_resolved):
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "依赖路径越出项目根，已拒绝。"},
        )
    # 敏感依赖拒绝（P1-3）：先于扩展名白名单——id_ed25519/*.pem 无白名单
    # 扩展名，也必须落 403 而非 unsupported 分支；命中不读内容、不返回大小。
    target_sensitive = security_guard.sensitive_path_reason(target)
    if target_sensitive is not None:
        return _sensitive_blocked_response(target_sensitive)
    # R2-6：依赖目标命中 .git/.lfs_checkpoints（任意段）或顶层 data → 403。
    target_runtime = _runtime_state_blocked_reason(target, root_resolved)
    if target_runtime is not None:
        return _sensitive_blocked_response(target_runtime)
    ext = target.suffix.lower()
    mime = _RELATED_MIME.get(ext)
    if mime is None:
        return UTF8JSONResponse(
            status_code=400,
            content={
                "error": "unsupported_related_type",
                "detail": "依赖打包仅支持 .js/.css 与图片/字体资产。",
            },
        )
    if not target.is_file():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "file_not_found", "detail": f"依赖文件不存在: {path}"},
        )
    try:
        blob = target.read_bytes()
    except OSError as exc:
        logger.exception("file related read failed: base=%s path=%s", base, path)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
        )
    if len(blob) > _RELATED_MAX_BYTES:
        return UTF8JSONResponse(
            status_code=413,
            content={
                "error": "related_too_large",
                "detail": f"依赖 {len(blob)} 字节超单资产上限 {_RELATED_MAX_BYTES} 字节，已拒绝（不截断）。",
            },
        )
    # 文本类（js/css，将内联进文档）须合法 UTF-8；二进制资产（图片/字体，
    # data URI 化）原样字节，不做解码校验。
    if ext not in _RELATED_BINARY_EXT:
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            return UTF8JSONResponse(
                status_code=415,
                content={"error": "not_text", "detail": "依赖不是合法 UTF-8 文本。"},
            )
    return UTF8JSONResponse(
        content={
            "type": "related",
            "path": str(target),
            "size": len(blob),
            "mime": mime,
            "content_base64": base64.b64encode(blob).decode("ascii"),
        }
    )


@preview_router.get("/api/v1/files/stat")
def stat_file(request: Request, path: str) -> Response:
    """文件版本指纹（对齐 DSH workspace-files.stat 的事实面）.

    返回 size + mtime_ns 供预览观察器比较（changes 流的轮询等价物：程序
    只报机械事实，不判断内容语义）。仅普通文件；缺路径/越界/目录如实报错；
    工作区未配置 → 503；敏感文件名命中 → 403（P1-3）。
    """
    if not path:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": "缺少 path。"},
        )
    engine = _engine_from(request)
    root_resolved = _workspace_root_or_none(engine)
    if root_resolved is None:
        return _workspace_unconfigured_response()
    target = _resolve_in_root(path, root_resolved)
    if target is None:
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "out_of_bounds", "detail": "路径越出项目根，已拒绝。"},
        )
    # 敏感文件拒绝（P1-3）：先于存在性检查（不泄露敏感文件存在性）；
    # 命中即 403，不返回 size/mtime 版本指纹。
    sensitive_reason = security_guard.sensitive_path_reason(target)
    if sensitive_reason is not None:
        return _sensitive_blocked_response(sensitive_reason)
    # R2-6：版本库元数据/运行时状态目录（.git/.lfs_checkpoints 任意段、data
    # 第 1 段）同样 403——不返回运行时状态文件（会话/日志/审计）的版本指纹。
    runtime_reason = _runtime_state_blocked_reason(target, root_resolved)
    if runtime_reason is not None:
        return _sensitive_blocked_response(runtime_reason)
    if not target.exists():
        return UTF8JSONResponse(
            status_code=404,
            content={"error": "file_not_found", "detail": f"文件不存在: {path}"},
        )
    if not target.is_file():
        return UTF8JSONResponse(
            status_code=400,
            content={"error": "not_regular_file", "detail": "目标不是普通文件。"},
        )
    try:
        st = target.stat()
    except OSError as exc:
        logger.exception("file stat failed: path=%s", path)
        return UTF8JSONResponse(
            status_code=500,
            content={"error": "read_failed", "detail": f"[程序异常] 读取失败（{type(exc).__name__}）。"},
        )
    return UTF8JSONResponse(
        content={
            "path": str(target),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        }
    )
