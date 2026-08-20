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


def _recognize_doc_images(images: list[tuple[str, bytes]]) -> str:
    """文档内图片视觉识别（2026-08-20 镜像, 用户定: 默认关 + 单文档 5 张上限）.

    文字层文档（PDF/docx）内的图片（报告截图/插图/图表）内容, 文本提取拿不到——
    每张图走 MiniMax 视觉转录, 追加标注到提取文本。单张失败跳过（不阻塞）。

    Returns:
        追加块（含来源标注）；开关关 / 无图 / 全失败 → ""。
    """
    import os as _os

    if _os.environ.get("WEB_DOC_IMAGE_RECOGNITION", "0").strip().lower() in (
        "0", "off", "false", "no",
    ):
        return ""
    try:
        max_n = max(1, min(20, int(_os.environ.get("WEB_DOC_IMAGE_MAX", "5"))))
    except ValueError:
        max_n = 5
    if not images:
        return ""
    from llm_loop.web.vision import _sniff_mime, describe_image

    parts: list[str] = []
    for name, img_bytes in images[:max_n]:
        try:
            text = describe_image(img_bytes, mime=_sniff_mime(img_bytes), settings=None)
            text = (text or "").strip()
            if text:
                parts.append(f"[文档图片识别: {name}]\n{text}")
        except Exception:  # noqa: BLE001 — 单张失败跳过
            continue
    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts)


def _collect_pdf_images(reader) -> list[tuple[str, bytes]]:
    """收集 PDF 页面内嵌图片（pypdf page.images; 失败/不支持 → 空）."""
    out: list[tuple[str, bytes]] = []
    try:
        for page in reader.pages[:50]:
            for im in page.images or []:
                try:
                    data = im.data if hasattr(im, "data") else bytes(im.image)
                    name = getattr(im, "name", "") or f"page_img_{len(out)}.png"
                    if data:
                        out.append((name, data))
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001 — 图片收集失败不影响文本
        return []
    return out


def _extract_docx(data: bytes, filename: str) -> ExtractResult:
    """docx 提取（zipfile + XML 标准库，零额外依赖）."""
    # 2026-08-20（借鉴 SYAGI P3-5）: zip 压缩炸弹防护——10MB 压缩包可膨胀为超大 XML,
    # 先查展开大小再读取。
    _DOCX_XML_MAX_BYTES = 20 * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            try:
                xml_info = zf.getinfo("word/document.xml")
            except KeyError as exc:
                return ExtractResult(
                    source_filename=filename,
                    content_type="docx",
                    status="error",
                    detail=f"[程序异常] docx 解析失败（{type(exc).__name__}: {exc}）。",
                )
            if xml_info.file_size > _DOCX_XML_MAX_BYTES:
                return ExtractResult(
                    source_filename=filename,
                    content_type="docx",
                    status="error",
                    detail=(
                        f"[程序异常] docx 内部 document.xml 展开超过 "
                        f"{_DOCX_XML_MAX_BYTES // 1024 // 1024}MB 上限，已拒绝解析。"
                    ),
                )
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except zipfile.BadZipFile as exc:
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
    # 2026-08-20（诚实性）: 空文档如实标注（对照 PDF 扫描件检查）
    if not text:
        return ExtractResult(
            source_filename=filename,
            content_type="docx",
            status="error",
            detail="docx 未提取到文字（文档可能全为图片/空文档）。",
        )
    # 2026-08-20: 文档内图片识别（默认关 + 5 张上限; 用户定）——word/media/* 提取
    media_images: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for n in zf.namelist():
                if n.startswith("word/media/") and n.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    try:
                        media_images.append((n.rsplit("/", 1)[-1], zf.read(n)))
                    except Exception:  # noqa: BLE001
                        continue
    except zipfile.BadZipFile:
        pass
    text += _recognize_doc_images(media_images)
    text, truncated = _truncate(text)
    return ExtractResult(
        source_filename=filename,
        content_type="docx",
        status="ok",
        result_text=text,
        truncated=truncated,
    )


def _extract_pdf_vision(data: bytes, filename: str) -> str | None:
    """扫描件 PDF 视觉转录兜底（2026-08-20 镜像）: macOS sips 渲染页面 → 图片识别转录.

    无文字层 PDF（扫描件/纯图片）用系统自带 sips 渲染成 PNG, 走 describe_image
    （MiniMax 视觉, 真实可用）转录页面文字。诚实标注来源（视觉转录 ≠ 文字层提取）。

    Returns:
        转录文本（非空）；渲染/识别失败 → None（调用方保持原 error 提示）。
    """
    import os as _os
    import shutil as _shutil
    import subprocess as _sp
    import tempfile as _tf

    if _shutil.which("sips") is None:
        return None
    if _os.environ.get("WEB_PDF_VISION_FALLBACK", "1").strip().lower() in ("0", "off", "false", "no"):
        return None
    tmp_pdf = None
    try:
        with _tf.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tmp_pdf = tf.name
            tf.write(data)
        out_png = tmp_pdf + ".png"
        proc = _sp.run(
            ["sips", "-s", "format", "png", tmp_pdf, "--out", out_png],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not Path(out_png).exists():
            return None
        from llm_loop.web.vision import _sniff_mime, describe_image

        img = Path(out_png).read_bytes()
        if not img:
            return None
        text = describe_image(img, mime=_sniff_mime(img), settings=None)
        text = text.strip()
        return text or None
    except Exception:  # noqa: BLE001 — 渲染/识别失败 → None（保持原 error 路径）
        return None
    finally:
        import contextlib as _ctx

        with _ctx.suppress(OSError):
            if tmp_pdf:
                Path(tmp_pdf).unlink(missing_ok=True)
                Path(tmp_pdf + ".png").unlink(missing_ok=True)


def _extract_pdf(data: bytes, filename: str) -> ExtractResult:
    """PDF 提取（pypdf 逐页，50 页上限对齐 本地既有实现）."""
    try:
        reader = PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
        max_pages = min(total_pages, PDF_MAX_PAGES)
        parts: list[str] = []
        pages_text: list[str] = []
        for i in range(max_pages):
            page_t = reader.pages[i].extract_text() or ""
            pages_text.append(page_t)
            parts.append(f"[第 {i + 1} 页]\n" + page_t)
        if total_pages > PDF_MAX_PAGES:
            parts.append(f"\n...[截断] PDF 共 {total_pages} 页，仅提取前 {PDF_MAX_PAGES} 页")
        text = "\n".join(parts).strip()
    except Exception as exc:  # pypdf 解析失败如实反馈（加密文档明确提示）
        detail = f"[程序异常] PDF 解析失败（{type(exc).__name__}: {exc}）。"
        if "encrypt" in str(exc).lower() or "password" in str(exc).lower():
            detail = "PDF 已加密（需密码），无法解析。请提供未加密或已解密的 PDF。"
        return ExtractResult(
            source_filename=filename,
            content_type="pdf",
            status="error",
            detail=detail,
        )
    # 2026-08-20（诚实性）: 无文字层 PDF（扫描件/纯图片）——先试视觉转录兜底,
    # 失败则如实标注 error（防幻觉 + 用户知情）。
    if not any(pt.strip() for pt in pages_text):
        try:
            vision_text = _extract_pdf_vision(data, filename)
        except Exception:  # noqa: BLE001 — 兜底失败保持 error
            vision_text = None
        if vision_text:
            return ExtractResult(
                source_filename=filename,
                content_type="pdf",
                status="ok",
                result_text=vision_text,
                detail="（扫描件 PDF 视觉转录，来源: 图片识别）",
            )
        return ExtractResult(
            source_filename=filename,
            content_type="pdf",
            status="error",
            detail=(
                "PDF 无文字层（可能是扫描件/纯图片文档），本地无法提取文字，"
                "视觉转录亦失败。可将 PDF 页面导出为图片走图片识别，"
                "或提供带文字层的 PDF。"
            ),
        )
    # 2026-08-20: 文字层 PDF 内嵌图片识别（默认关 + 5 张上限; 用户定）
    text += _recognize_doc_images(_collect_pdf_images(reader))
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
    2026-08-20: 默认不启用（WEB_DOC_BACKEND 默认 local）——arkcli 未登录时不再白跑。
    """
    import json as _json
    import os as _os
    import shutil as _shutil
    import subprocess as _sp
    import tempfile as _tf

    # 2026-08-20: 默认 local（本地解析优先, fail-open 已有）；arkcli 结构化抽取仅显式
    # WEB_DOC_BACKEND=arkcli 时启用（未登录账号不占默认链, 同 vision 调整原则）
    if _os.environ.get("WEB_DOC_BACKEND", "local").strip().lower() != "arkcli":
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
