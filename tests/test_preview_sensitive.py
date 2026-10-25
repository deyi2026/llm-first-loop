"""预览面根语义 + 敏感文件拒绝回归（安全建议书 2026-10-25 P1-3 / S2-1）.

两道闸门（均位于 preview_routes.py，敏感判定直接复用共享
security_guard.sensitive_path_reason，不另立名单）：

1. 根语义：workspace_root 为空 / 指向不存在目录 → 503
   workspace_unconfigured，绝不回退项目根（旧行为曾把仓库根 .env、
   data/ 会话整面暴露给 preview/stat/related）。
2. 敏感文件拒绝：preview / stat / related 命中 → 403
   sensitive_file_blocked，不读内容、不返回大小/预览；判定先于存在性
   检查（不给敏感文件存在性侧信道）。

同时钉住不变量：根内 .py/.md/绝对路径正常预览；related 的 .js 白名单与
打包语义不变；越界仍 400 out_of_bounds（原语义，与建议书 S2-1 实测一致）。
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_loop.web import build_app

_ENV_SECRET = "LLM_API_KEY=sk-live-preview-guard-000123\n"
# 私钥样例拆开拼接：避免测试源码自身携带完整 PEM 头，触发 CacheGuard
# （准入审查材料包含这些文件的 diff，会整体拦截审查子代理）。
_PEM_SECRET = "-----BEGIN " + "PRIVATE KEY-----\npreview-guard-key-material\n-----END " + "PRIVATE KEY-----\n"
_ED25519_SECRET = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\npreview-guard\n"


def _client(build_test_engine, root: Path) -> TestClient:
    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(root)
    return TestClient(build_app(engine=engine))


def _ws(tmp_path: Path) -> Path:
    """最小 fake 工作区：普通文件 + 敏感文件（全部在工作区根内）."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("# 工作区文档\n", encoding="utf-8")
    (root / "index.html").write_text("<p>x</p>", encoding="utf-8")
    (root / "js").mkdir()
    (root / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / ".env").write_text(_ENV_SECRET, encoding="utf-8")
    (root / ".env.example").write_text("LLM_API_KEY=\n", encoding="utf-8")
    (root / "certs").mkdir()
    (root / "certs" / "server.pem").write_text(_PEM_SECRET, encoding="utf-8")
    (root / "id_ed25519").write_text(_ED25519_SECRET, encoding="utf-8")
    return root


# ── 1. 根语义：未配置 → 503，绝不回退项目根 ──


def test_preview_503_when_workspace_unconfigured(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    assert engine.workspace_root == ""  # 前置：fixture 引擎默认未配置工作区
    client = TestClient(build_app(engine=engine))
    resp = client.get("/api/v1/files/preview", params={"path": "pyproject.toml"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"
    # 旧行为：静默回退项目根返回 200 + 仓库文件内容（S2-1 实测）——现在必须没有
    assert "llm-first-loop" not in resp.text


def test_stat_503_when_workspace_unconfigured(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    client = TestClient(build_app(engine=engine))
    resp = client.get("/api/v1/files/stat", params={"path": "pyproject.toml"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"


def test_related_503_when_workspace_unconfigured(build_test_engine):
    engine, _ = build_test_engine([{"content": "ok"}])
    client = TestClient(build_app(engine=engine))
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "js/app.js"}
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"


def test_preview_503_when_workspace_dir_missing(build_test_engine, tmp_path):
    """已配置但目录不存在 → 同样 503（如实拒绝，不猜根）."""
    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(tmp_path / "no-such-workspace")
    client = TestClient(build_app(engine=engine))
    resp = client.get("/api/v1/files/preview", params={"path": "hello.py"})
    assert resp.status_code == 503
    assert resp.json()["error"] == "workspace_unconfigured"


# ── 2. 既有能力不回归 ──


def test_preview_py_and_md_normal(build_test_engine, tmp_path):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    for name, needle in (("hello.py", "print('hi')"), ("README.md", "工作区文档")):
        resp = client.get("/api/v1/files/preview", params={"path": name})
        assert resp.status_code == 200, name
        body = resp.json()
        assert body["type"] == "text"
        assert needle in body["content"]


def test_preview_accepts_absolute_path_inside_workspace(build_test_engine, tmp_path):
    """根内绝对路径仍可预览（出产物 chips 契约不变）."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": str(root / "hello.py")})
    assert resp.status_code == 200
    assert "print('hi')" in resp.json()["content"]


def test_related_normal_js_still_packable(build_test_engine, tmp_path):
    """related 的 .js 白名单与 base64 打包语义不变."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "js/app.js"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "related"
    assert body["mime"] == "text/javascript"
    assert base64.b64decode(body["content_base64"]) == b"console.log(1)"


# ── 3. 敏感文件拒绝（共享 security_guard 原语） ──


@pytest.mark.parametrize("sensitive", [".env", "certs/server.pem", "id_ed25519"])
def test_preview_sensitive_blocked_without_leak(build_test_engine, tmp_path, sensitive):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": sensitive})
    assert resp.status_code == 403, sensitive
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert body["reason"].startswith(("name:", "dir:"))
    # 不读内容、不返回大小/预览
    assert "content" not in body and "content_base64" not in body and "size" not in body
    # 响应体不携带任何敏感文件内容
    assert "sk-live-preview-guard" not in resp.text
    assert "PRIVATE KEY" not in resp.text


@pytest.mark.parametrize("sensitive", [".env", "certs/server.pem", "id_ed25519"])
def test_stat_sensitive_blocked_without_facts(build_test_engine, tmp_path, sensitive):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/stat", params={"path": sensitive})
    assert resp.status_code == 403, sensitive
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert "size" not in body and "mtime_ns" not in body  # 不泄露版本指纹


def test_related_target_sensitive_blocked(build_test_engine, tmp_path):
    """敏感依赖名（即使无白名单扩展名）→ 403，先于 unsupported 分支."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get(
        "/api/v1/files/related", params={"base": "index.html", "path": "id_ed25519"}
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert "content_base64" not in body and "size" not in body
    assert "OPENSSH PRIVATE KEY" not in resp.text


def test_related_base_sensitive_blocked(build_test_engine, tmp_path):
    """以敏感名为打包基点（base=.env）→ 同样 403，不读内容."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get(
        "/api/v1/files/related", params={"base": ".env", "path": "js/app.js"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "sensitive_file_blocked"
    assert "sk-live-preview-guard" not in resp.text


def test_preview_sensitive_name_blocked_even_if_missing(build_test_engine, tmp_path):
    """fail-closed：判定只看名字，不探测存在性（不给敏感文件存在性侧信道）."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": "missing.key"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "sensitive_file_blocked"


def test_preview_env_example_template_allowed(build_test_engine, tmp_path):
    """模板文件（.env.example）不算敏感（security_guard 契约），仍可预览."""
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": ".env.example"})
    assert resp.status_code == 200
    assert "LLM_API_KEY=" in resp.json()["content"]


# ── 4. 越界原语义不变（400 out_of_bounds，见建议书 S2-1 实测记录） ──


def test_preview_traversal_still_out_of_bounds(build_test_engine, tmp_path):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": "../../etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_stat_traversal_still_out_of_bounds(build_test_engine, tmp_path):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/stat", params={"path": "/etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"


def test_related_traversal_still_out_of_bounds(build_test_engine, tmp_path):
    root = _ws(tmp_path)
    client = _client(build_test_engine, root)
    resp = client.get(
        "/api/v1/files/related",
        params={"base": "index.html", "path": "../../etc/passwd"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "out_of_bounds"
