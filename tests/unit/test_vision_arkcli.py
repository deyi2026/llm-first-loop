"""vision arkcli 后端测试（2026-08-15：团队自研多模态工具接入）.

mock subprocess：成功扁平 schema 解析 / 鉴权失败指引 / 超时 / minimax opt-in 保持。
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from llm_loop.web import vision


def _proc(out: str, code: int = 0, err: str = "") -> mock.MagicMock:
    p = mock.MagicMock()
    p.stdout = out
    p.stderr = err
    p.returncode = code
    return p


def test_arkcli_backend_success_parses_content(monkeypatch):
    """成功：扁平 schema content 解析返回."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "arkcli")
    data = json.dumps({"id": "r1", "model": "doubao-seed-1-6", "content": "图片内容：红色方块", "usage": {}})
    with mock.patch("llm_loop.web.vision.subprocess.run", return_value=_proc(data)) as run:
        text = vision.describe_image(b"PNGDATA", mime="image/png", prompt="描述")
    assert text == "图片内容：红色方块"
    # 命令行含 image-caption + @临时文件 + no-progress + format json
    cmd = run.call_args.args[0]
    assert cmd[1] == "+understand" and cmd[2] == "image-caption"
    assert cmd[4].startswith("@") and cmd[4].endswith(".png")
    assert "--no-progress" in cmd and "--format" in cmd


def test_arkcli_auth_failure_gives_actionable_hint(monkeypatch):
    """鉴权失败（SSO 过期）→ RuntimeError 附登录指引."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "arkcli")
    err = json.dumps({"ok": False, "error": {"type": "error", "message": "not logged in, SSO token expired"}})
    with (
        mock.patch("llm_loop.web.vision.subprocess.run", return_value=_proc("", code=1, err=err)),
        pytest.raises(RuntimeError) as ei,
    ):
        vision.describe_image(b"PNGDATA", prompt="描述")
    msg = str(ei.value)
    assert "not logged in" in msg
    assert "arkcli auth login volc-sso" in msg  # 可操作指引


def test_arkcli_timeout_reports(monkeypatch):
    """超时 → RuntimeError（如实）."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "arkcli")
    with (
        mock.patch(
            "llm_loop.web.vision.subprocess.run",
            side_effect=__import__("subprocess").TimeoutExpired("arkcli", 60),
        ),
        pytest.raises(RuntimeError) as ei,
    ):
        vision.describe_image(b"PNGDATA", prompt="描述")
    assert "超时" in str(ei.value)


def test_arkcli_missing_cli_hint(monkeypatch):
    """arkcli 不在 PATH → 明确提示."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "arkcli")
    with (
        mock.patch("llm_loop.web.vision.shutil.which", return_value=None),
        pytest.raises(RuntimeError) as ei,
    ):
        vision.describe_image(b"PNGDATA", prompt="描述")
    assert "arkcli 未安装" in str(ei.value)


def test_minimax_backend_opt_in_preserved(monkeypatch):
    """WEB_VISION_BACKEND=minimax → 旧路径保留（httpx 调用）."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    with mock.patch("llm_loop.web.vision.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": "描述文本"}}]}
        text = vision.describe_image(b"PNGDATA", prompt="描述")
    assert text == "描述文本"


def test_doc_extract_arkcli_priority_then_local_fallback(monkeypatch, tmp_path):
    """文档识别：arkcli 优先；失败 → 本地提取兜底（fail-open）."""
    from llm_loop.web import upload_handlers as uh

    pdf_bytes = b"%PDF-1.4 fake"  # 本地提取将失败 → error；arkcli 失败也走本地（如实）
    monkeypatch.setenv("WEB_DOC_BACKEND", "arkcli")
    # arkcli 抽取不可用（返回 None）→ 本地路径兜底（不抛）
    with mock.patch("llm_loop.web.upload_handlers._extract_doc_arkcli", return_value=None):
        r = uh.process_upload("x.pdf", pdf_bytes)
    assert r.status in ("ok", "error")  # 本地兜底结果（fake pdf → error 如实）


# ── provider 后端（注册表 multimodal 模型，2026-08-15：Kimi 视觉实测可用） ──

def _settings_with_kimi_multimodal(tmp_path, monkeypatch, key_env: str = "KIMI_API_KEY"):
    """构造含 multimodal kimi 模型的 settings（写 providers.json 到 data_dir）."""
    import json as _json

    from llm_loop.config import load_settings

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "providers.json").write_text(
        _json.dumps(
            {
                "kimi": {
                    "base_url": "https://api.kimi.com/coding/v1",
                    "api_key_env": key_env,
                    "models": {
                        "k3": {"context": 131072, "multimodal": True},
                        "k3-256k": {"context": 262144, "multimodal": True},
                    },
                },
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key_env": "LLM_API_KEY",
                    "models": {"deepseek-v4-flash": {"context": 131072, "multimodal": False}},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    return load_settings()


def test_provider_backend_picks_multimodal_model(tmp_path, monkeypatch):
    """provider 后端：扫描注册表选 multimodal 模型（跳过缺 key 与非多模态）."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "provider")
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")
    monkeypatch.setenv("LLM_API_KEY", "k-ds")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    settings = _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    assert vision.vision_enabled(settings) is True
    with mock.patch("llm_loop.web.vision.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": "红色"}}]}
        post.return_value.text = "{}"
        text = vision.describe_image(b"PNG", mime="image/png", prompt="颜色", settings=settings)
    assert text == "红色"
    url = post.call_args.args[0]
    assert "api.kimi.com" in url and url.endswith("/chat/completions")
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "k3"
    assert payload["messages"][0]["content"][0]["type"] == "image_url"


def test_provider_backend_no_multimodal_disabled(tmp_path, monkeypatch):
    """注册表无 multimodal 模型 → vision_enabled False（如实）."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "provider")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    # 清掉 kimi 的 multimodal 标记（模拟无视觉模型）
    import json as _json

    data_dir = tmp_path / "data"
    d = _json.loads((data_dir / "providers.json").read_text(encoding="utf-8"))
    d["kimi"]["models"]["k3"]["multimodal"] = False
    d["kimi"]["models"]["k3-256k"]["multimodal"] = False
    (data_dir / "providers.json").write_text(_json.dumps(d), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    from llm_loop.config import load_settings

    settings2 = load_settings()
    assert vision.vision_enabled(settings2) is False


def test_provider_backend_explicit_model(tmp_path, monkeypatch):
    """WEB_VISION_MODEL=provider/model 显式指定优先."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "provider")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")
    monkeypatch.setenv("LLM_API_KEY", "k-ds")
    monkeypatch.setenv("WEB_VISION_MODEL", "kimi/k3-256k")
    settings = _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    with mock.patch("llm_loop.web.vision.httpx.post") as post:
        post.return_value.status_code = 200
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
        post.return_value.text = "{}"
        vision.describe_image(b"PNG", prompt="x", settings=settings)
    assert post.call_args.kwargs["json"]["model"] == "k3-256k"


# ── auto 自动链（2026-08-15：团队识别工具优先，模型兜底） ──

def test_auto_chain_arkcli_auth_failure_falls_back_to_provider(tmp_path, monkeypatch):
    """auto：arkcli 未认证 → 自动降级注册表视觉模型（kimi）并成功."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "auto")
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")
    monkeypatch.setenv("LLM_API_KEY", "k-ds")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    settings = _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    auth_err = json.dumps({"ok": False, "error": {"message": "not logged in, SSO token expired"}})
    with (
        mock.patch("llm_loop.web.vision.shutil.which", return_value="/bin/arkcli"),
        mock.patch("llm_loop.web.vision.subprocess.run", return_value=_proc("", code=1, err=auth_err)),
        mock.patch("llm_loop.web.vision.httpx.post") as post,
    ):
        post.return_value.status_code = 200
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {"choices": [{"message": {"content": "红色（kimi 兜底）"}}]}
        post.return_value.text = "{}"
        text = vision.describe_image(b"PNG", prompt="颜色", settings=settings)
    assert text == "红色（kimi 兜底）"
    assert "api.kimi.com" in post.call_args.args[0]


def test_auto_chain_tool_first_when_ok(monkeypatch, tmp_path):
    """auto：arkcli 可用且成功 → 工具优先（不调 provider）."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "auto")
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")
    monkeypatch.setenv("LLM_API_KEY", "k-ds")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    settings = _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    ok = json.dumps({"content": "工具识别文本"})
    with (
        mock.patch("llm_loop.web.vision.shutil.which", return_value="/bin/arkcli"),
        mock.patch("llm_loop.web.vision.subprocess.run", return_value=_proc(ok)),
        mock.patch("llm_loop.web.vision.httpx.post") as post,
    ):
        text = vision.describe_image(b"PNG", prompt="颜色", settings=settings)
    assert text == "工具识别文本"
    post.assert_not_called()


def test_auto_chain_both_fail_gives_hint(monkeypatch, tmp_path):
    """auto：工具未认证且模型不可用 → 组合错误 + 登录指引."""
    monkeypatch.setenv("WEB_VISION_BACKEND", "auto")
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")
    monkeypatch.setenv("LLM_API_KEY", "k-ds")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    settings = _settings_with_kimi_multimodal(tmp_path, monkeypatch)
    auth_err = json.dumps({"ok": False, "error": {"message": "not logged in, SSO token expired"}})
    with (
        mock.patch("llm_loop.web.vision.shutil.which", return_value="/bin/arkcli"),
        mock.patch("llm_loop.web.vision.subprocess.run", return_value=_proc("", code=1, err=auth_err)),
        mock.patch("llm_loop.web.vision.httpx.post") as post,
    ):
        post.return_value.status_code = 500
        post.return_value.raise_for_status.side_effect = RuntimeError("boom")
        post.return_value.text = "err"
        with pytest.raises(RuntimeError) as ei:
            vision.describe_image(b"PNG", prompt="颜色", settings=settings)
    assert "arkcli 未认证" in str(ei.value)
    assert "arkcli auth login volc-sso" in str(ei.value)
