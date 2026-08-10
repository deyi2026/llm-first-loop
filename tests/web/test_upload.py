"""上传端点测试（M39，Mock/降级路径，零真实 API 调用）.

用例：校验/文本提取/docx 提取/PDF 提取/图片无 key 降级/图片识别 Mock/失败如实。
FakeLLM 装配复用 tests/web 既有模式；不调用真实视觉 API（Mock describe_image）。
"""

import base64

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _make_client(engine):
    return TestClient(build_app(engine=engine))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _upload(client, filename, data: bytes):
    return client.post("/api/v1/upload", json={"filename": filename, "data": _b64(data)})


def test_upload_text_ok(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "notes.txt", "你好，这是内容".encode("utf-8"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["content_type"] == "text"
    assert "你好，这是内容" in body["result_text"]
    assert body["source_filename"] == "notes.txt"


def test_upload_text_markdown(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "doc.md", "# 标题\n**加粗**".encode("utf-8"))
    assert resp.status_code == 200
    assert resp.json()["content_type"] == "text"
    assert "# 标题" in resp.json()["result_text"]


def test_upload_docx_ok(build_test_engine, fake_settings):
    import zipfile

    engine, _ = build_test_engine([])
    client = _make_client(engine)
    buf = bytes()
    # 最小 docx（word/document.xml 含文本）
    import io

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>docx内容</w:t></w:r></w:p></w:body></w:document>")
    resp = _upload(client, "test.docx", bio.getvalue())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["content_type"] == "docx"
    assert "docx内容" in body["result_text"]


def test_upload_docx_bad_zip(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "bad.docx", b"not a zip")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "docx 解析失败" in body["detail"]


def test_upload_pdf_ok(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    # 用 pypdf 生成最小 PDF
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    import io as _io

    bio = _io.BytesIO()
    writer.write(bio)
    resp = _upload(client, "test.pdf", bio.getvalue())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["content_type"] == "pdf"


def test_upload_pdf_corrupt(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "bad.pdf", b"%PDF-1.4 garbage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "PDF 解析失败" in body["detail"]


def test_upload_image_no_key_degraded(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "photo.png", b"fake-png-bytes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert "MINIMAX_API_KEY" in body["detail"]


def test_upload_oversize(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "big.txt", b"x" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 400
    assert "10MB" in resp.json()["detail"]


def test_upload_unsupported_ext(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "file.exe", b"MZ")
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


def test_upload_invalid_base64(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/upload", json={"filename": "a.txt", "data": "!!!not-base64!!!"})
    assert resp.status_code == 400
    assert "base64" in resp.json()["detail"]


def test_upload_no_filename(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = client.post("/api/v1/upload", json={"filename": "", "data": "aGk="})
    assert resp.status_code == 422


def test_upload_no_engine_call(build_test_engine, fake_settings):
    """上传端点不调用 engine.run（独立于核心对话链路）."""
    engine, fake = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "notes.txt", "hello".encode())
    assert resp.status_code == 200
    assert len(fake.calls) == 0  # 上传不触发 LLM 主链路


def test_upload_image_mocked_vision(build_test_engine, fake_settings, monkeypatch):
    """Mock 视觉识别：有 key 时返回识别文本（零真实 API 调用）."""
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    import llm_loop.web.vision as vision_mod

    def fake_describe(image_bytes, mime, prompt=""):
        return "图片描述：一只猫"

    monkeypatch.setattr(vision_mod, "describe_image", fake_describe)
    resp = _upload(client, "cat.png", b"fake-png-bytes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["content_type"] == "image"
    assert "一只猫" in body["result_text"]


def test_upload_image_vision_fails_degraded(build_test_engine, fake_settings, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    import llm_loop.web.vision as vision_mod

    def boom(image_bytes, mime, prompt=""):
        raise RuntimeError("vision api down")

    monkeypatch.setattr(vision_mod, "describe_image", boom)
    resp = _upload(client, "cat.png", b"fake-png-bytes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert "图片识别失败" in body["detail"]


def test_upload_truncate_long_text(build_test_engine, fake_settings):
    engine, _ = build_test_engine([])
    client = _make_client(engine)
    resp = _upload(client, "long.txt", ("x" * 100_001).encode())
    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is True
    assert "[截断]" in body["result_text"]