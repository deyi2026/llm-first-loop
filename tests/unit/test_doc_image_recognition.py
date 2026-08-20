"""2026-08-20（用户定: 默认关 + 5 张上限）: 文档内图片识别（PDF page.images / docx media）."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from llm_loop.web.upload_handlers import (
    _extract_docx,
    _extract_pdf,
    _recognize_doc_images,
)


def _make_img_bytes() -> bytes:
    img = Image.new("RGB", (100, 50), "white")
    ImageDraw.Draw(img).text((10, 20), "IMG 42", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf_with_image() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "TEXT LINE")
    c.drawImage(ImageReader(io.BytesIO(_make_img_bytes())), 100, 600, width=100, height=50)
    c.save()
    return buf.getvalue()


def _make_docx_with_image() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:p><w:t>docx text</w:t></w:p>")
        zf.writestr("word/media/image1.png", _make_img_bytes())
    return buf.getvalue()


def test_recognize_disabled_by_default(monkeypatch):
    """默认关: 不调视觉, 返回空追加块."""
    monkeypatch.delenv("WEB_DOC_IMAGE_RECOGNITION", raising=False)
    assert _recognize_doc_images([("a.png", b"x")]) == ""


def test_recognize_enabled_with_limit(monkeypatch):
    """开 + 上限 5: 最多识别 5 张, 结果含来源标注."""
    import llm_loop.web.upload_handlers as uh
    import llm_loop.web.vision as vision_mod

    monkeypatch.setenv("WEB_DOC_IMAGE_RECOGNITION", "1")
    monkeypatch.setenv("WEB_DOC_IMAGE_MAX", "5")
    calls: list[str] = []

    def fake_describe(image_bytes, mime, settings=None):
        calls.append(mime)
        return "图片内容: IMG 42"

    monkeypatch.setattr(vision_mod, "describe_image", fake_describe)
    monkeypatch.setattr(vision_mod, "_sniff_mime", lambda b: "image/png")

    out = _recognize_doc_images([("a.png", b"1"), ("b.png", b"2")] * 3)
    assert len(calls) == 5  # 上限 5
    assert "文档图片识别" in out


def test_pdf_image_appended_when_enabled(monkeypatch):
    """文字层 PDF 内嵌图片 → 开关开时追加识别块."""
    import llm_loop.web.upload_handlers as uh
    import llm_loop.web.vision as vision_mod

    monkeypatch.setenv("WEB_DOC_IMAGE_RECOGNITION", "1")
    monkeypatch.setattr(vision_mod, "describe_image", lambda *a, **k: "IMG 42 内容")
    monkeypatch.setattr(vision_mod, "_sniff_mime", lambda b: "image/png")

    r = _extract_pdf(_make_pdf_with_image(), "mixed.pdf")
    assert r.status == "ok"
    assert "TEXT LINE" in (r.result_text or "")
    assert "文档图片识别" in (r.result_text or "")


def test_docx_image_appended_when_enabled(monkeypatch):
    """docx media 图片 → 开关开时追加识别块."""
    import llm_loop.web.upload_handlers as uh
    import llm_loop.web.vision as vision_mod

    monkeypatch.setenv("WEB_DOC_IMAGE_RECOGNITION", "1")
    monkeypatch.setattr(vision_mod, "describe_image", lambda *a, **k: "IMG 42 内容")
    monkeypatch.setattr(vision_mod, "_sniff_mime", lambda b: "image/png")

    r = _extract_docx(_make_docx_with_image(), "mixed.docx")
    assert r.status in ("ok", "success")
    assert "docx text" in (r.result_text or "")
    assert "文档图片识别" in (r.result_text or "")


def test_images_not_appended_when_disabled(monkeypatch):
    """默认关: 文档内图片不识别（文本照常提取）."""
    r = _extract_pdf(_make_pdf_with_image(), "mixed.pdf")
    assert r.status == "ok"
    assert "TEXT LINE" in (r.result_text or "")
    assert "文档图片识别" not in (r.result_text or "")
