"""2026-08-20（诚实性）: 无文字层 PDF（扫描件）如实标注 error——不返回空 ok 致模型困惑/猜测."""

from __future__ import annotations

from pathlib import Path

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


def test_scanned_pdf_vision_transcription_success(monkeypatch):
    """扫描件 PDF + 视觉可用 → 转录成功（诚实标注来源）."""
    import llm_loop.web.upload_handlers as uh
    import llm_loop.web.vision as vision_mod

    # mock: sips 存在 + 渲染产出 + 视觉转录成功（函数内 import 的是顶层 shutil/subprocess）
    import shutil as _sh
    monkeypatch.setattr(_sh, "which", lambda name: "/usr/bin/sips" if name == "sips" else None)
    monkeypatch.setenv("WEB_PDF_VISION_FALLBACK", "1")
    print("DEBUG shutil.which(sips):", _sh.which("sips"))

    def fake_render(args, capture_output, text, timeout):
        print("DEBUG fake_render called, out in args:", "--out" in args)
        out = args[args.index("--out") + 1]
        Path(out).write_bytes(b"\x89PNG\r\n\x1a\nfake-png")
        return type("P", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", fake_render)
    monkeypatch.setattr(vision_mod, "describe_image", lambda *a, **k: "扫描件转录文字: HELLO 2026")
    monkeypatch.setattr(vision_mod, "_sniff_mime", lambda b: "image/png")

    scanned = b"""%PDF-1.4
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
    r = uh._extract_pdf(scanned, "scan.pdf")
    print("DEBUG status:", r.status, "detail:", r.detail[:80])
    vt = uh._extract_pdf_vision(scanned, "scan.pdf")
    print("DEBUG vision_text:", repr(vt))
    assert r.status == "ok"
    assert "HELLO 2026" in (r.result_text or "")
    assert "视觉转录" in r.detail  # 诚实标注来源


def test_scanned_pdf_vision_fallback_disabled(monkeypatch):
    """WEB_PDF_VISION_FALLBACK=0 → 不尝试视觉, 直接 error（原诚实路径）."""
    import llm_loop.web.upload_handlers as uh

    monkeypatch.setenv("WEB_PDF_VISION_FALLBACK", "0")
    scanned = b"""%PDF-1.4
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
    r = uh._extract_pdf(scanned, "scan.pdf")
    assert r.status == "error"
    assert "无文字层" in r.detail
