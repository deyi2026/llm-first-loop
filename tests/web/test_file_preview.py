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


# ── readRelated（对齐 DSH workspace-files.readRelated：HTML 相对依赖打包） ──


def test_related_resolves_against_base_dir(build_test_engine, tmp_path):
    """相对路径基于 base 文件所在目录解析（含 ../ 上跳）."""
    import base64

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "docs").mkdir()
    (root / "js").mkdir()
    (root / "docs" / "page.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
    resp = client.get(
        "/api/v1/files/related",
        params={"base": "docs/page.html", "path": "../js/app.js"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "related"
    assert body["mime"] == "text/javascript"
    assert base64.b64decode(body["content_base64"]) == b"console.log(1)"


def test_related_css_mime(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "style.css").write_text("body{color:red}", encoding="utf-8")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "style.css"}
    )
    body = resp.json()
    assert body["mime"] == "text/css"


def test_related_rejects_escape_outside_root(build_test_engine, tmp_path):
    """../ 越出工作区根 → 400 out_of_bounds（与 preview 同安全边界）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "../../etc/passwd"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_related_missing_404(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "nope.js"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "file_not_found"


def test_related_rejects_non_packable_extension(build_test_engine, tmp_path):
    """只允许打包面内扩展名（.js/.css/图片/字体；机械扩展名门）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "evil.exe").write_bytes(b"MZ")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "evil.exe"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_related_type"


# ── 版本变更监听（对齐 DSH changes 流的事实面）：stat 版本指纹 + 响应携带 mtime ──


def test_preview_text_response_carries_mtime(build_test_engine, tmp_path):
    """文本页携带 mtime_ns（读前 stat 版本指纹，消费方可辨新旧页）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "t.txt").write_text("x\n", encoding="utf-8")
    resp = client.get("/api/v1/files/preview", params={"path": "t.txt"})
    body = resp.json()
    assert isinstance(body["mtime_ns"], int)
    assert body["mtime_ns"] > 0


def test_preview_bytes_response_carries_mtime(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "p.png").write_bytes(b"PNG")
    resp = client.get("/api/v1/files/preview", params={"path": "p.png"})
    assert isinstance(resp.json()["mtime_ns"], int)


def test_stat_returns_version_facts(build_test_engine, tmp_path):
    """stat 端点返回 size+mtime_ns（前端观察器比较版本指纹用）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "t.txt").write_text("hello", encoding="utf-8")
    resp = client.get("/api/v1/files/stat", params={"path": "t.txt"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["size"] == 5
    assert isinstance(body["mtime_ns"], int) and body["mtime_ns"] > 0

    # 变更后指纹变化（机械事实，不判断语义）
    import os
    import time

    (root / "t.txt").write_text("hello world", encoding="utf-8")
    os.utime(root / "t.txt", ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
    body2 = client.get("/api/v1/files/stat", params={"path": "t.txt"}).json()
    assert body2["size"] == 11
    assert body2["mtime_ns"] != body["mtime_ns"]


def test_stat_missing_404(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    resp = client.get("/api/v1/files/stat", params={"path": "gone.txt"})
    assert resp.status_code == 404


def test_stat_rejects_out_of_bounds(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    resp = client.get("/api/v1/files/stat", params={"path": "/etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_stat_dir_not_regular_file(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "d").mkdir()
    resp = client.get("/api/v1/files/stat", params={"path": "d"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "not_regular_file"


# ── CSS url() 资产打包：readRelated 放开图片/字体（二进制，不做 UTF-8 校验） ──


def test_related_allows_binary_image_without_utf8_check(build_test_engine, tmp_path):
    """png 字节（含非 UTF-8 序列）原样 base64 返回，mime image/png."""
    import base64

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    blob = b"\x89PNG\r\n\x1a\n\xff\xfe binary"
    (root / "bg.png").write_bytes(blob)
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "bg.png"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mime"] == "image/png"
    assert base64.b64decode(body["content_base64"]) == blob


def test_related_font_mime(build_test_engine, tmp_path):
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "f.woff2").write_bytes(b"wOF2")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "f.woff2"}
    )
    body = resp.json()
    assert body["mime"] == "font/woff2"


def test_related_css_resolves_against_css_file_dir(build_test_engine, tmp_path):
    """css 内 url() 的 base 应为该 css 文件（前端递归打包依赖此契约）."""
    import base64

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "css").mkdir()
    (root / "css" / "main.css").write_text("body{}", encoding="utf-8")
    (root / "css" / "img").mkdir()
    (root / "css" / "img" / "bg.png").write_bytes(b"PNG")
    resp = client.get(
        "/api/v1/files/related",
        params={"base": "css/main.css", "path": "img/bg.png"},
    )
    assert resp.status_code == 200
    assert base64.b64decode(resp.json()["content_base64"]) == b"PNG"


def test_related_per_asset_cap_413(build_test_engine, tmp_path, monkeypatch):
    """单资产超 4MiB 上限 → 413 拒绝（不截断冒充完整）."""
    from llm_loop.web import preview_routes

    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "big.js").write_bytes(b"//" + b"x" * 64)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    monkeypatch.setattr(preview_routes, "_RELATED_MAX_BYTES", 8)
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "big.js"}
    )
    assert resp.status_code == 413
    assert resp.json()["error"] == "related_too_large"
    assert "content_base64" not in resp.json()


def test_related_rejects_non_utf8(build_test_engine, tmp_path):
    """依赖资产须为合法 UTF-8（内联进 iframe 前置校验，对齐 DSH fail-not-partial）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "bin.js").write_bytes(b"\xff\xfe invalid")
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "bin.js"}
    )
    assert resp.status_code == 415
    assert resp.json()["error"] == "not_text"


def test_related_rejects_missing_base(build_test_engine, tmp_path):
    """base 不存在/越界 → 拒绝（不猜目录）."""
    root, client = _ws_client(build_test_engine, tmp_path)
    resp = client.get(
        "/api/v1/files/related", params={"base": "ghost.html", "path": "a.js"}
    )
    assert resp.status_code == 404
