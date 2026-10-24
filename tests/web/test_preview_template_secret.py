"""N11（2026-10-25 第四轮红队）：模板后缀名字豁免不得洗白真实密钥内容.

红队实测：`.env` 内容经 cp/改写落到 `*.example` 名下后，preview 的模板
后缀豁免（security_guard._TEMPLATE_SUFFIXES）名字层直接放行，返回 200 +
明文密钥。修复：模板后缀形态在 preview 时对内容做强密钥特征复核
（security_guard.has_strong_secret），命中 → 403 sensitive_file_blocked，
不读内容、不返回大小/预览；占位符模板（无强密钥）仍 200。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.web import build_app

# 强密钥样本（与 security_guard._STRONG_CONTENT_PATTERNS 对齐；不含真实凭证）
_STRONG_ANTHROPIC = "ANTHROPIC_API_KEY=sk-ant-api03-REDTEAM-ROUND4-" + "x" * 24 + "\n"
_AWS_KEY_ID = "AK" + "IAIOSFODNN7EXAMPLE"  # 运行时拼接，源码不携带完整字面量
_STRONG_AWS = "AWS_ACCESS_KEY_ID=" + _AWS_KEY_ID + "\n"
# 拼接书写：源码自身不携带完整 PEM 头（CacheGuard 会拦审查材料）
_PRIVATE_KEY = "-----BEGIN " + "PRIVATE KEY-----\nround4-template-wash-probe\n-----END " + "PRIVATE KEY-----\n"


def _client(build_test_engine, root: Path) -> TestClient:
    engine, _ = build_test_engine([{"content": "ok"}])
    engine.workspace_root = str(root)
    return TestClient(build_app(engine=engine))


def _ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def test_cp_env_content_to_example_name_is_blocked(build_test_engine, tmp_path):
    """`cp .env note.example` 后预览 note.example：内容含强密钥 → 403 不泄露."""
    root = _ws(tmp_path)
    (root / ".env").write_text(_STRONG_ANTHROPIC, encoding="utf-8")
    (root / "note.example").write_text(_STRONG_ANTHROPIC, encoding="utf-8")  # 模拟 cp 洗白

    resp = _client(build_test_engine, root).get(
        "/api/v1/files/preview", params={"path": "note.example"}
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert body["reason"].startswith("content:strong-secret")
    # 不读内容、不返回大小/预览；响应体不携带任何密钥明文
    assert "content" not in body and "content_base64" not in body and "size" not in body
    assert "sk-ant-api03" not in resp.text


def test_env_example_with_real_secret_is_blocked(build_test_engine, tmp_path):
    """`.env.example` 名下出现真实密钥（改名洗白常见形态）→ 403 不泄露."""
    root = _ws(tmp_path)
    (root / ".env.example").write_text(_STRONG_AWS, encoding="utf-8")

    resp = _client(build_test_engine, root).get(
        "/api/v1/files/preview", params={"path": ".env.example"}
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert _AWS_KEY_ID not in resp.text
    assert "content" not in body and "size" not in body


def test_template_private_key_block_is_blocked(build_test_engine, tmp_path):
    """`.sample` 模板名下整块私钥 → 403（强特征覆盖私钥块形态）."""
    root = _ws(tmp_path)
    (root / "deploy.sample").write_text(_PRIVATE_KEY, encoding="utf-8")

    resp = _client(build_test_engine, root).get(
        "/api/v1/files/preview", params={"path": "deploy.sample"}
    )
    assert resp.status_code == 403, resp.text
    assert "PRIVATE KEY" not in resp.text


def test_env_example_placeholder_still_previewed(build_test_engine, tmp_path):
    """正常占位符模板（无强密钥）不受影响：仍 200 且可读内容（既有契约）."""
    root = _ws(tmp_path)
    (root / ".env.example").write_text("LLM_API_KEY=replace-me\n", encoding="utf-8")
    (root / "README.md").write_text("ok\n", encoding="utf-8")

    client = _client(build_test_engine, root)
    resp = client.get("/api/v1/files/preview", params={"path": ".env.example"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "text"
    assert "LLM_API_KEY=replace-me" in body["content"]
    # 普通文件不含强密钥时照常预览
    assert client.get("/api/v1/files/preview", params={"path": "README.md"}).status_code == 200


def test_cp_env_content_to_plain_md_is_blocked(build_test_engine, tmp_path):
    """第四轮红队 M9：复制成任意普通名（a.md）也必须按内容拦，名字层不可作为白名单入口."""
    root = _ws(tmp_path)
    (root / ".env").write_text(_STRONG_ANTHROPIC, encoding="utf-8")
    (root / "a.md").write_text(_STRONG_ANTHROPIC, encoding="utf-8")  # 模拟 cp 洗白

    resp = _client(build_test_engine, root).get(
        "/api/v1/files/preview", params={"path": "a.md"}
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["error"] == "sensitive_file_blocked"
    assert "sk-ant-api03" not in resp.text
    assert "content" not in body and "size" not in body
