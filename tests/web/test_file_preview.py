"""Web V2 出产物文件预览端点测试（对齐 DSH deliverables 点击打开）.

覆盖：正常读取（相对/工作区根内绝对）/ 根外绝对拒绝 / 越界拒绝 / 不存在 404。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.web import build_app


def _client(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    return TestClient(build_app(engine=engine))


def test_preview_normal_file(build_test_engine):
    """项目根内相对路径正常返回内容."""
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "pyproject.toml"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "pyproject.toml"
    assert "llm-first-loop" in body["content"]
    assert body["truncated"] is False


def test_preview_accepts_absolute_path_in_root(build_test_engine):
    """工作区根内的绝对路径可预览（出产物 chips 用绝对路径）."""
    client = _client(build_test_engine)
    # R9-IMM-02 适配：conftest chdir 沙箱后 cwd≠仓库根，锚定 __file__ 取根内文件绝对路径
    from pathlib import Path

    abs_path = str(Path(__file__).resolve().parents[2] / "pyproject.toml")
    resp = client.get("/api/v1/files/preview", params={"path": abs_path})
    assert resp.status_code == 200
    assert "llm-first-loop" in resp.json()["content"]


def test_preview_rejects_absolute_path_outside_root(build_test_engine):
    """根外绝对路径拒绝（resolve 越界校验）."""
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "/etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_preview_rejects_parent_traversal(build_test_engine):
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "../.env"})
    assert resp.status_code == 400


def test_preview_missing_file_404(build_test_engine):
    client = _client(build_test_engine)
    resp = client.get("/api/v1/files/preview", params={"path": "no_such_file_xyz.txt"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "file_not_found"



def test_preview_basename_fallback_rejects_symlink_escape(build_test_engine, tmp_path):
    """裸文件名兜底不得把工作区内symlink解析到根外后读取。"""
    root = tmp_path / "workspace"
    docs = root / "docs"
    docs.mkdir(parents=True)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SECRET-OUTSIDE-WORKSPACE", encoding="utf-8")
    (docs / "secret-link.txt").symlink_to(outside)

    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(root)
    client = TestClient(build_app(engine=engine))
    resp = client.get(
        "/api/v1/files/preview", params={"path": "secret-link.txt"}
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"
    assert "SECRET-OUTSIDE-WORKSPACE" not in resp.text


# ── 对齐 DSH workspace-files/documentpreview：分页/多格式预览回归 ──


def _ws_client(build_test_engine, tmp_path):
    """临时工作区 + 绑定 engine.workspace_root 的 TestClient."""
    root = tmp_path / "workspace"
    root.mkdir()
    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(root)
    return root, TestClient(build_app(engine=engine))


def test_preview_text_paging_monotonic(build_test_engine, tmp_path):
    """文本按 1-based 行分页：页间不重叠、eof 单调收敛（对齐 DSH read 分页语义）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "ten.txt").write_text("\n".join(f"line-{i}" for i in range(1, 11)), encoding="utf-8")

    seen: list[str] = []
    offset, eof = 1, False
    for _ in range(10):
        resp = client.get(
            "/api/v1/files/preview", params={"path": "ten.txt", "offset": offset, "limit": 3}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "text"
        assert body["offset"] == offset
        seen.extend(body["content"].split("\n"))
        offset += body["lines"]
        eof = body["eof"]
        if eof:
            break
    assert eof is True
    assert seen == [f"line-{i}" for i in range(1, 11)]  # 不重叠不遗漏


def test_preview_text_paging_rejects_bad_range(build_test_engine, tmp_path):
    """非法 offset/limit（0/负/超上限）→ 400，不静默纠正."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "t.txt").write_text("a\nb\n", encoding="utf-8")
    for params in (
        {"offset": 0, "limit": 10},
        {"offset": -1, "limit": 10},
        {"offset": 1, "limit": 0},
        {"offset": 1, "limit": -5},
        {"offset": 1, "limit": 5001},
    ):
        resp = client.get("/api/v1/files/preview", params={"path": "t.txt", **params})
        assert resp.status_code == 400, params
        assert resp.json()["error"] == "invalid_range"


def test_preview_text_page_reports_eof_on_small_file(build_test_engine, tmp_path):
    """小文件默认参数整页返回，eof=true、truncated=false（兼容旧字段）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "small.txt").write_text("hello\nworld\n", encoding="utf-8")
    resp = client.get("/api/v1/files/preview", params={"path": "small.txt"})
    body = resp.json()
    assert body["eof"] is True
    assert body["truncated"] is False
    assert body["content"] == "hello\nworld"


def test_preview_pdf_complete_bytes(build_test_engine, tmp_path):
    """PDF 以完整字节（base64）返回，不落文本替换读取."""
    import base64

    root, client = _ws_client(build_test_engine, tmp_path)
    blob = b"%PDF-1.4 fake-bytes"
    (root / "doc.pdf").write_bytes(blob)
    resp = client.get("/api/v1/files/preview", params={"path": "doc.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "pdf"
    assert body["mime"] == "application/pdf"
    assert base64.b64decode(body["content_base64"]) == blob
    assert body["size"] == len(blob)


def test_preview_bytes_too_large_rejected_not_truncated(build_test_engine, tmp_path, monkeypatch):
    """超完整字节上限的 pdf/html/图片必须拒绝（413），不得截断冒充完整."""
    from llm_loop.web import preview_routes

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "big.pdf").write_bytes(b"%PDF" + b"x" * 64)
    monkeypatch.setattr(preview_routes, "_PREVIEW_BYTES_MAX", 8)
    resp = client.get("/api/v1/files/preview", params={"path": "big.pdf"})
    assert resp.status_code == 413
    assert resp.json()["error"] == "file_too_large"
    assert "content_base64" not in resp.json()


def test_preview_html_complete_bytes(build_test_engine, tmp_path):
    """HTML 以完整字节返回（前端沙箱 iframe 渲染）."""
    import base64

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "page.html").write_text("<h1>标题</h1><script>1</script>", encoding="utf-8")
    resp = client.get("/api/v1/files/preview", params={"path": "page.html"})
    body = resp.json()
    assert body["type"] == "html"
    assert body["mime"] == "text/html"
    assert b"<h1>" in base64.b64decode(body["content_base64"])


def test_preview_known_binary_unsupported_without_read(build_test_engine, tmp_path):
    """已知无渲染器的二进制（zip/音视频/office）→ unsupported 空态，绝不读内容."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "arc.zip").write_bytes(b"PK\x03\x04 not really a zip")
    resp = client.get("/api/v1/files/preview", params={"path": "arc.zip"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "unsupported_binary"
    assert "content" not in body and "content_base64" not in body


def test_preview_rejects_non_utf8_text(build_test_engine, tmp_path):
    """非 UTF-8 且未知扩展 → not_text（415），不用替换字符冒充文本."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "blob.dat").write_bytes(b"\xff\xfe\xfa binary-garbage")
    resp = client.get("/api/v1/files/preview", params={"path": "blob.dat"})
    assert resp.status_code == 415
    assert resp.json()["error"] == "not_text"


def test_preview_rejects_nul_in_text(build_test_engine, tmp_path):
    """合法 UTF-8 但含 NUL → not_text（对齐 DSH 文本页拒绝 NUL）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "nul.log").write_text("line1\n\x00line2\n", encoding="utf-8")
    resp = client.get("/api/v1/files/preview", params={"path": "nul.log"})
    assert resp.status_code == 415
    assert resp.json()["error"] == "not_text"


def test_preview_image_bmp_mime(build_test_engine, tmp_path):
    """BMP 补入图片 MIME 表（对齐 DSH 图片渲染器集合）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "x.bmp").write_bytes(b"BM fake-bitmap")
    resp = client.get("/api/v1/files/preview", params={"path": "x.bmp"})
    body = resp.json()
    assert body["type"] == "image"
    assert body["mime"] == "image/bmp"


def test_preview_dir_listing(build_test_engine, tmp_path):
    """目录 → 单层列表（chips 引用目录时可浏览）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "inner.txt").write_text("x", encoding="utf-8")
    (root / "top.txt").write_text("y", encoding="utf-8")
    resp = client.get("/api/v1/files/preview", params={"path": "sub"})
    body = resp.json()
    assert body["type"] == "dir"
    assert body["files"] == [{"name": "inner.txt", "size": 1}]
    assert body["parent"] == "."
