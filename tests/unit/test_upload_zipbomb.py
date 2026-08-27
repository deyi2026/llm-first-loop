"""2026-08-20（借鉴 SYAGI P3-5）: docx zip 压缩炸弹防护——document.xml 展开超限拒绝解析."""

from __future__ import annotations

import io
import zipfile

from llm_loop.web.upload_handlers import MAX_UPLOAD_BYTES, _extract_docx


def _make_docx_with_big_xml(size: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:p>padding</w:p>" + b"x" * size)
    return buf.getvalue()


def test_extract_docx_rejects_oversize_uncompressed_xml():
    """展开超过 20MB 的 document.xml → 拒绝解析（返回 error 而非膨胀内存）."""
    # 造一个 file_size 超过 20MB 的 entry（内容用稀疏数据避免真占 20MB）
    # zipfile.writestr 会真实写入, 改用压满零的重复块（压缩后很小）
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"<w:p>x</w:p>" + b"\x00" * (21 * 1024 * 1024))
    data = buf.getvalue()
    assert len(data) < MAX_UPLOAD_BYTES  # 压缩后远小于 10MB 上传上限（证明炸弹形态）
    result = _extract_docx(data, "bomb.docx")
    assert result.status == "error"
    assert "上限" in result.detail and "拒绝" in result.detail


def test_extract_docx_normal_docx_still_works():
    """正常小 docx 不受影响."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:p><w:t>hello</w:t></w:p>")
    result = _extract_docx(buf.getvalue(), "ok.docx")
    assert result.status in ("ok", "success")
    assert "hello" in (result.result_text or "")
