"""文档提取模块（M39，借鉴 本地既有实现 doc_parser.py 算法思路，引用非改写）.

支持：纯文本直读（UTF-8）/ docx（zipfile+XML 标准库）/ PDF（pypdf 逐页，50 页上限）。
失败如实 fail-open（返回错误信息而非抛异常静默），10MB 大小上限 + 100K 字符截断标注。
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader  # type: ignore[reportMissingImports]

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
MAX_EXTRACT_CHARS = 100_000
PDF_MAX_PAGES = 50

_TEXT_EXTS = frozenset(
    {
        ".txt",
        ".md",
        ".json",
        ".csv",
        ".log",
        ".py",
        ".js",
        ".ts",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".html",
        ".xml",
        ".sh",
        ".sql",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
    }
)
_DOCX_EXTS = frozenset({".docx"})
_PDF_EXTS = frozenset({".pdf"})
_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

SUPPORTED_IMAGE_EXTS = sorted(_IMAGE_EXTS)


@dataclass
class ExtractResult:
    """文档提取结果（来源可追溯 + 状态如实）."""

    source_filename: str
    content_type: str
    status: str  # ok / degraded / error
    result_text: str = ""
    detail: str = ""
    truncated: bool = False
    page_count: int | None = None


def file_ext(filename: str) -> str:
    """返回文件扩展名（小写）."""
    return Path(filename).suffix.lower()


def validate_upload_b64_size(data_b64: str) -> str | None:
    """P2-2(2026-08-15，审计发现)：base64 体积前置检查（解码前）.

    base64 编码体积 ≈ 原始 4/3——先查字符串长度再解码，超限直接拒绝，
    避免大 payload 先吃解码内存/CPU 再被体积拒（解码后 validate_upload 仍兜底）。
    """
    # base64 含换行/填充余量：+16 字符宽限（标准 4 字符组 + padding）
    if len(data_b64) > (MAX_UPLOAD_BYTES * 4) // 3 + 16:
        return (
            f"文件超过 10MB 上限（base64 前置估算 {len(data_b64)} 字符 "
            f"≈ {len(data_b64) * 3 // 4} 字节）。"
        )
    return None


def validate_upload(filename: str, data: bytes) -> str | None:
    """上传校验：大小 + 扩展名类型。返回错误信息（None = 通过）."""
    if len(data) > MAX_UPLOAD_BYTES:
        return f"文件超过 10MB 上限（{len(data)} 字节）。"
    ext = file_ext(filename)
    if not ext:
        return "无法识别文件类型（无扩展名）。"
    if ext not in _TEXT_EXTS | _DOCX_EXTS | _PDF_EXTS | _IMAGE_EXTS:
        return f"不支持的文件类型（.{ext}）。支持：文本/图片/docx/PDF。"
    return None


def _truncate(text: str) -> tuple[str, bool]:
    """超长截断标注（100K 字符上限）."""
    if len(text) <= MAX_EXTRACT_CHARS:
        return text, False
    return text[:MAX_EXTRACT_CHARS] + "\n...[截断] 内容过长已截断", True


def _extract_text(data: bytes, filename: str) -> ExtractResult:
    """纯文本直读（UTF-8 解码，失败回退 utf-8-sig/latin-1）."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")  # 兜底字节解码，如实标注
    text, truncated = _truncate(text)
    return ExtractResult(
        source_filename=filename,
        content_type="text",
        status="ok",
        result_text=text,
        truncated=truncated,
    )


def _extract_docx(data: bytes, filename: str) -> ExtractResult:
    """docx 提取（zipfile + XML 标准库，零额外依赖）."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        return ExtractResult(
            source_filename=filename,
            content_type="docx",
            status="error",
            detail=f"[程序异常] docx 解析失败（{type(exc).__name__}: {exc}）。",
        )
    # 极简 XML 文本提取：段落/文本节点（不引入 lxml）
    text = xml.replace("</w:p>", "\n").replace("</w:tr>", "\n")
    text = text.replace("</w:tc>", " | ").replace("<w:br/>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text, truncated = _truncate(text)
    return ExtractResult(
        source_filename=filename,
        content_type="docx",
        status="ok",
        result_text=text,
        truncated=truncated,
    )


def _extract_pdf(data: bytes, filename: str) -> ExtractResult:
    """PDF 提取（pypdf 逐页，50 页上限对齐 本地既有实现）."""
    try:
        reader = PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
        max_pages = min(total_pages, PDF_MAX_PAGES)
        parts: list[str] = []
        for i in range(max_pages):
            parts.append(f"[第 {i + 1} 页]\n" + (reader.pages[i].extract_text() or ""))
        if total_pages > PDF_MAX_PAGES:
            parts.append(f"\n...[截断] PDF 共 {total_pages} 页，仅提取前 {PDF_MAX_PAGES} 页")
        text = "\n".join(parts).strip()
    except Exception as exc:  # pypdf 解析失败如实反馈
        return ExtractResult(
            source_filename=filename,
            content_type="pdf",
            status="error",
            detail=f"[程序异常] PDF 解析失败（{type(exc).__name__}: {exc}）。",
        )
    text, truncated = _truncate(text)
    return ExtractResult(
        source_filename=filename,
        content_type="pdf",
        status="ok",
        result_text=text,
        truncated=truncated,
        page_count=min(total_pages, PDF_MAX_PAGES),
    )


def _extract_doc_arkcli(data: bytes, filename: str, prompt: str) -> str | None:
    """arkcli +understand doc-extract 结构化抽取（2026-08-15 团队自研工具）.

    返回抽取文本；CLI 缺失/调用失败/解析失败 → None（调用方本地提取兜底，fail-open）。
    鉴权失败也走兜底（本地文本提取仍有真实内容，不伪装 arkcli 成功）。
    """
    import json as _json
    import os as _os
    import shutil as _shutil
    import subprocess as _sp
    import tempfile as _tf

    if _os.environ.get("WEB_DOC_BACKEND", "arkcli").strip().lower() == "local":
        return None
    if _shutil.which("arkcli") is None:
        return None
    ext = Path(filename).suffix.lower() or ".pdf"
    tmp_path: str | None = None
    try:
        with _tf.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(data)
        cmd = [
            "arkcli", "+understand", "doc-extract", "--input", f"@{tmp_path}",
            prompt, "--no-progress", "--format", "json",
        ]
        import contextlib as _ctx

        try:
            with _ctx.suppress(ValueError):
                timeout = max(30.0, float(_os.environ.get("WEB_DOC_TIMEOUT", "120")))
            proc = _sp.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except Exception:  # noqa: BLE001 — 工具不可用/超时 → 本地兜底
            return None
        for out in (proc.stdout, proc.stderr):
            if not out.strip():
                continue
            try:
                parsed = _json.loads(out)
            except _json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("content"):
                return str(parsed["content"]).strip()
        return None
    finally:
        # 审查中危修复: 临时文件在 finally 清理（原实现成功/异常 return 路径
        # 不执行 unlink → 临时文件泄漏，长期运行累积磁盘）
        if tmp_path:
            import contextlib as _ctx

            with _ctx.suppress(OSError):
                _os.unlink(tmp_path)


def process_upload(filename: str, data: bytes) -> ExtractResult:
    """上传文件类型分发（文本/docx/PDF/图片）。图片由 vision 模块处理，此处返回降级提示."""
    ext = file_ext(filename)
    if ext in _TEXT_EXTS:
        return _extract_text(data, filename)
    if ext in _DOCX_EXTS:
        ark = _extract_doc_arkcli(
            data, filename,
            "抽取文档关键信息：标题/核心要点/关键字段（保留原文细节，输出结构化文本）",
        )
        if ark:
            return ExtractResult(
                source_filename=filename,
                content_type="docx",
                status="ok",
                result_text=ark,
                detail="（arkcli doc-extract 结构化抽取）",
            )
        return _extract_docx(data, filename)
    if ext in _PDF_EXTS:
        ark = _extract_doc_arkcli(
            data, filename,
            "抽取文档关键信息：标题/核心要点/关键字段（保留原文细节，输出结构化文本）",
        )
        if ark:
            return ExtractResult(
                source_filename=filename,
                content_type="pdf",
                status="ok",
                result_text=ark,
                detail="（arkcli doc-extract 结构化抽取）",
            )
        return _extract_pdf(data, filename)
    if ext in _IMAGE_EXTS:
        return ExtractResult(
            source_filename=filename,
            content_type="image",
            status="pending",  # 图片走视觉识别（vision 模块），调用方分发
            detail=f"图片（.{ext}），待视觉识别处理",
        )
    return ExtractResult(
        source_filename=filename,
        content_type=ext.lstrip(".") or "unknown",
        status="error",
        detail=f"不支持的文件类型（.{ext}）。",
    )
