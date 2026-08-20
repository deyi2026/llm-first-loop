"""2026-08-20（诚实性）: 无文字层 PDF（扫描件）如实标注 error——不返回空 ok 致模型困惑/猜测."""

from __future__ import annotations

from llm_loop.web.upload_handlers import _extract_pdf

_SCANNED_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
200
%%EOF"""


def test_scanned_pdf_reports_error_with_reason():
    """无文字层 PDF → error + 明确原因（防模型猜测/幻觉）."""
    r = _extract_pdf(_SCANNED_PDF, "scan.pdf")
    assert r.status == "error"
    assert "无文字层" in r.detail
    assert "扫描件" in r.detail
    assert "图片" in r.detail  # 指引可走图片通道


def test_text_pdf_still_extracts():
    """带文字层 PDF 不受影响."""
    data = open("/tmp/test_text_pdf.pdf", "rb").read()
    r = _extract_pdf(data, "text.pdf")
    assert r.status == "ok"
    assert "HELLO PDF TEXT LAYER" in (r.result_text or "")
