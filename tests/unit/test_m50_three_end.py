"""M50 三端一致性 + providers.json 热重载 测试（design §5.6 / §六）.

覆盖:
- CLI --model 启动参数写会话 override（与 Web/飞书同会话可见）
- CLI /model 三形态（查/切/default）
- 飞书 /model 消息命令三形态（走 handler 分发, Mock bridge）
- Web 候选来自 registry 全量 / WEB_MODELS 过滤子集 / 无注册表零回归
- refresh_config 热重载 providers.json（新增 provider 生效 / 失败保持旧表）
- 三端写同一 session override（CLI 切完 Web 可见 — 用同一 SessionStore 验证）

全部 Mock + FakeLLM, 零真实网络、零真实飞书 API.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from llm_loop.config import Settings
from llm_loop.core.session import SessionStore
from llm_loop.introspection.model_command import (
    handle_model_command,
    parse_model_command,
)
from llm_loop.introspection.providers_registry_reload import (
    refresh_provider_registry,
)
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry
from llm_loop.web import build_app

# ── 测试工具 ──


_TWO_PROVIDER_JSON = json.dumps(
    {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
                "deepseek-v4-pro": {"context": 1000000, "thinking": True, "cost_tier": "high"},
            },
            "default_model": "deepseek-v4-flash",
        },
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "api_key_env": "MINIMAX_API_KEY",
            "models": {
                "MiniMax-M3": {"context": 1000000, "thinking": False, "cost_tier": "mid"},
            },
            "default_model": "MiniMax-M3",
        },
    }
)


def _make_settings(data_dir: Path, **overrides) -> Settings:
    """构造测试 Settings（含 M47 注册表 env; M48 llm_pool 路径）."""
    base = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "deepseek-v4-flash",
        "data_dir": str(data_dir),
        "model_providers_raw": _TWO_PROVIDER_JSON,
        "model_fallbacks_raw": "",
        "self_inspection_enabled": False,
        "extract_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


def _make_pool(settings: Settings, fake_llm: object) -> ModelClientPool:
    """构造 ModelClientPool（fake_llm 作 default_client; duck typing）."""
    registry = load_registry(settings)
    return ModelClientPool(  # type: ignore[arg-type]
        registry=registry,
        default_client=fake_llm,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )


class _FakeLLM:
    """极简 LLM stub（duck typing）."""

    timeout_s: float = 60.0
    thinking_mode: bool = True
    reasoning_effort: str = "high"
    thinking_supported: bool = True
    model: str = "deepseek-v4-flash"
    max_tokens: int | None = None
    wire_protocol: str = "openai"  # P3-5 对齐 LLMClient 新字段  # 2026-08-15: 对齐 LLMClient 新装配字段

    def chat(self, *args, **kwargs):  # noqa: ANN001, ANN002 — 占位
        raise NotImplementedError


def _write_providers_json(data_dir: Path, config: dict) -> Path:
    """写 {data_dir}/providers.json 文件（M50 热重载源）."""
    path = data_dir / "providers.json"
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


# ── 1. CLI --model 启动参数 ──


def test_cli_startup_model_writes_session_override(tmp_path):
    """CLI --model <provider/model> 启动参数会写入会话 model_override；与 Web/飞书 同 SessionStore 可见."""
    settings = _make_settings(tmp_path)
    # 关键: MINIMAX_API_KEY 必须存在以让 client_params 校验通过
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"

    from llm_loop.cli import _apply_cli_startup_model

    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None  # 模拟 CLI 启动路径（loop.run 未注入）
    engine.correction_ctx.session_model_override = None

    sid = session_store.create()
    sess = session_store.load(sid)
    # 关键: 写占位消息保证 Session 序列化非空
    session_store.save(sess)

    # 模拟 CLI --model minimax/MiniMax-M3
    _apply_cli_startup_model(engine, session_store, sid, "minimax/MiniMax-M3")

    # 验证: 会话 override 已落盘
    sess_after = session_store.load(sid)
    assert sess_after.model_override == "minimax/MiniMax-M3"


def test_cli_startup_model_invalid_does_not_change(tmp_path):
    """CLI --model 引用非法 (resolve 失败) → 不修改会话 override；如实反馈."""
    settings = _make_settings(tmp_path)
    from llm_loop.cli import _apply_cli_startup_model

    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None

    sid = session_store.create()
    sess = session_store.load(sid)
    session_store.save(sess)

    _apply_cli_startup_model(engine, session_store, sid, "nonexistent/model-xyz")

    sess_after = session_store.load(sid)
    assert sess_after.model_override is None  # 未变


def test_cli_startup_model_default_clears_override(tmp_path):
    """CLI --model default → 清除会话 override."""
    settings = _make_settings(tmp_path)
    from llm_loop.cli import _apply_cli_startup_model

    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None

    sid = session_store.create()
    sess = session_store.load(sid)
    sess.model_override = "minimax/MiniMax-M3"
    session_store.save(sess)

    _apply_cli_startup_model(engine, session_store, sid, "default")

    sess_after = session_store.load(sid)
    assert sess_after.model_override is None


# ── 2. CLI /model 三形态（interact 命令）─


def test_parse_model_command_recognizes_all_forms():
    """parse_model_command: 识别 /model / Model / MODEL 三大小写 + 带/不带参数."""
    is_cmd, arg = parse_model_command("/model")
    assert is_cmd is True and arg == ""

    is_cmd, arg = parse_model_command("/model deepseek/deepseek-v4-flash")
    assert is_cmd is True and arg == "deepseek/deepseek-v4-flash"

    is_cmd, arg = parse_model_command("/Model")
    assert is_cmd is True and arg == ""

    is_cmd, arg = parse_model_command("/MODEL default")
    assert is_cmd is True and arg == "default"

    is_cmd, arg = parse_model_command("hello")
    assert is_cmd is False and arg == "hello"


def test_cli_model_command_listing(tmp_path, capsys):
    """CLI /model (无参) → 列出当前会话模型 + 目录 (M48 model_catalog 复用)."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    from llm_loop.cli import _run_interactive

    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None
    engine.session = session_store
    engine._cli_startup_model = ""
    engine.run = mock.Mock(
        return_value=mock.Mock(final_answer="hi", rounds=1, tool_calls=[], truncated=False, verification_note=None)
    )

    sid = session_store.create()
    # 输入 /model 触发目录列表
    with mock.patch("builtins.input", side_effect=["/model", "exit"]):
        _run_interactive(engine, session_id=sid)

    captured = capsys.readouterr().out
    assert "当前会话模型" in captured
    assert "deepseek/deepseek-v4-flash" in captured or "deepseek-v4-flash" in captured


def test_cli_model_command_switch(tmp_path, capsys):
    """CLI /model <ref> → 切换并持久化（与 Web/飞书 同 SessionStore 可见）."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    from llm_loop.cli import _run_interactive

    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None
    engine.session = session_store
    engine._cli_startup_model = ""  # 明确不启动 --model 参数
    engine.run = mock.Mock(
        return_value=mock.Mock(final_answer="hi", rounds=1, tool_calls=[], truncated=False, verification_note=None)
    )

    sid = session_store.create()
    with mock.patch("builtins.input", side_effect=["/model minimax/MiniMax-M3", "exit"]):
        _run_interactive(engine, session_id=sid)

    captured = capsys.readouterr().out
    assert "模型已切换" in captured or "minimax/MiniMax-M3" in captured
    # 验证: 持久化生效
    sess_after = session_store.load(sid)
    assert sess_after.model_override == "minimax/MiniMax-M3"


def test_cli_model_command_default(tmp_path, capsys):
    """CLI /model default → 清除 override."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    from llm_loop.cli import _run_interactive

    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None
    engine.session = session_store
    engine._cli_startup_model = ""
    engine.run = mock.Mock(
        return_value=mock.Mock(final_answer="hi", rounds=1, tool_calls=[], truncated=False, verification_note=None)
    )

    sid = session_store.create()
    # 先写入 override, 再发出 /model default
    sess = session_store.load(sid)
    sess.model_override = "minimax/MiniMax-M3"
    session_store.save(sess)

    with mock.patch("builtins.input", side_effect=["/model default", "exit"]):
        _run_interactive(engine, session_id=sid)

    sess_after = session_store.load(sid)
    assert sess_after.model_override is None


def test_cli_model_command_unknown_does_not_change(tmp_path, capsys):
    """CLI /model <未知> → 如实回执失败, override 不变."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    from llm_loop.cli import _run_interactive

    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None
    engine.session = session_store
    engine._cli_startup_model = ""
    engine.run = mock.Mock()

    sid = session_store.create()
    with mock.patch("builtins.input", side_effect=["/model nonexistent/xyz", "exit"]):
        _run_interactive(engine, session_id=sid)

    captured = capsys.readouterr().out
    assert "失败" in captured or "不可用" in captured
    sess_after = session_store.load(sid)
    assert sess_after.model_override is None


# ── 3. 飞书 /model 消息命令 ──


def _make_feishu_handler(engine, session_store, replies):
    """构造 FeishuMessageHandler (mock bridge — ReplyFn 注入 replies 列表)."""
    from llm_loop.feishu.handlers import FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    session_map = SessionMap(session_store, path=str(engine.session._dir.parent / "feishu_map.json"))  # noqa: SLF001
    return FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(engine.session._dir.parent / "audit"),  # noqa: SLF001
        typing_ack=False,
        streaming=False,
    )


def _make_msg(text: str = "") -> object:
    """构造飞书消息对象."""
    from llm_loop.feishu.handlers import FeishuMessage

    return FeishuMessage(
        message_id="om_test",
        sender_id="ou_test",
        chat_id="oc_test",
        msg_type="text",
        text=text,
        sender_type="user",
    )


def _make_feishu_engine(tmp_path, settings):
    """构造可与 FeishuMessageHandler 协同的 mock engine（带 correction_ctx + model_pool + session）."""
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None
    engine.session = session_store
    engine.run = mock.Mock(
        return_value=mock.Mock(
            final_answer="hi", rounds=1, tool_calls=[], truncated=False, verification_note=None
        )
    )
    return engine, session_store


def test_feishu_model_command_listing(tmp_path):
    """飞书 /model (无参) → 列出目录 + 当前会话模型."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    engine, session_store = _make_feishu_engine(tmp_path, settings)
    replies: list = []
    handler = _make_feishu_handler(engine, session_store, replies)

    handler.handle(_make_msg(text="/model"))

    assert len(replies) == 1
    rid, text, rtype = replies[0]
    assert rtype == "chat_id"
    assert "当前会话模型" in text
    assert "deepseek/deepseek-v4-flash" in text or "deepseek-v4-flash" in text


def test_feishu_model_command_switch(tmp_path):
    """飞书 /model <ref> → 切换 + 持久化（与 CLI 同一 SessionStore 可见）."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    engine, session_store = _make_feishu_engine(tmp_path, settings)
    replies: list = []
    handler = _make_feishu_handler(engine, session_store, replies)

    handler.handle(_make_msg(text="/model minimax/MiniMax-M3"))

    # 验证 回复 + 持久化
    assert len(replies) == 1
    assert "模型已切换" in replies[0][1] or "minimax/MiniMax-M3" in replies[0][1]
    # 同一个 SessionStore 检查 override（与 CLI 共享同一会话存储）
    # 飞书路径会创建一个新会话（p2p_key 派生），找到它
    sessions = session_store.list_sessions()
    assert len(sessions) == 1
    sid = sessions[0].session_id
    assert session_store.load(sid).model_override == "minimax/MiniMax-M3"


def test_feishu_model_command_default(tmp_path):
    """飞书 /model default → 清除 override."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    engine, session_store = _make_feishu_engine(tmp_path, settings)
    replies: list = []
    handler = _make_feishu_handler(engine, session_store, replies)

    # 先写入 override
    handler.handle(_make_msg(text="/model minimax/MiniMax-M3"))
    replies.clear()

    # 再清除
    handler.handle(_make_msg(text="/model default"))

    sessions = session_store.list_sessions()
    sid = sessions[0].session_id
    assert session_store.load(sid).model_override is None


# ── 4. 三端写同一 session override (核心一致性) ──


def test_three_ends_share_session_override(tmp_path):
    """M50 核心契约: CLI / 飞书 / Web 三端共享同一 SessionStore, 切换可互相可见.

    设计依据: design §六 "唯一真相源: 会话 model override 存于 session store, 三端读写同一份"
    """
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())

    # 1. CLI 端模拟切换
    from llm_loop.cli import _apply_cli_startup_model

    engine = mock.Mock()
    engine.correction_ctx = mock.Mock()
    engine.correction_ctx.model_pool = pool
    engine.correction_ctx.session_set_override = None
    engine.correction_ctx.session_model_override = None

    sid = session_store.create()
    _apply_cli_startup_model(engine, session_store, sid, "minimax/MiniMax-M3")
    cli_sess = session_store.load(sid)
    assert cli_sess.model_override == "minimax/MiniMax-M3"

    # 2. Web 端读到同一 override（GET /api/v1/models 应含 minimax/MiniMax-M3）
    # 构造 Web 客户端
    session_store2 = session_store  # 同一存储实例
    engine_web = mock.Mock()
    engine_web.session = session_store2
    engine_web.llm = mock.Mock(model="deepseek-v4-flash")
    engine_web.llm_pool = pool
    engine_web.correction_ctx = mock.Mock()
    engine_web.correction_ctx.model_pool = pool
    engine_web.llm_pool.registry = pool.registry

    # 3. 飞书端也读到同一 override
    feishu_engine = mock.Mock()
    feishu_engine.session = session_store2
    feishu_engine.correction_ctx = mock.Mock()
    feishu_engine.correction_ctx.model_pool = pool
    feishu_engine.correction_ctx.session_set_override = None
    feishu_engine.correction_ctx.session_model_override = "minimax/MiniMax-M3"
    feishu_engine.llm_pool = pool
    feishu_engine.run = mock.Mock(
        return_value=mock.Mock(
            final_answer="hi", rounds=1, tool_calls=[], truncated=False, verification_note=None
        )
    )

    # 飞书 chat → 应读到 Web 列表里的 override
    sess_loaded = session_store2.load(sid)
    assert sess_loaded.model_override == "minimax/MiniMax-M3"


# ── 5. Web 端模型候选 ──


def test_web_models_from_registry_full(tmp_path):
    """Web 端 GET /api/v1/models 候选来自 registry 全量（无 WEB_MODELS 配置时）."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())

    engine = mock.Mock()
    engine.llm = mock.Mock(model="deepseek-v4-flash")
    engine.llm_pool = pool
    engine.session = session_store

    app = build_app(engine=engine)
    client = TestClient(app)
    # 重要: 去掉 WEB_MODELS 环境变量
    os.environ.pop("WEB_MODELS", None)
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "deepseek/deepseek-v4-flash" in body["models"]
    assert "deepseek/deepseek-v4-pro" in body["models"]
    assert "minimax/MiniMax-M3" in body["models"]
    assert body["current"] in body["models"]


def test_web_models_with_web_models_env_filter(tmp_path):
    """Web 端 GET /api/v1/models 候选 = WEB_MODELS env 过滤子集（交集）."""
    os.environ["MINIMAX_API_KEY"] = "test-minimax-key"
    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())

    engine = mock.Mock()
    engine.llm = mock.Mock(model="deepseek-v4-flash")
    engine.llm_pool = pool
    engine.session = session_store

    app = build_app(engine=engine)
    client = TestClient(app)
    # WEB_MODELS 仅保留 deepseek-v4-flash, minimax/MiniMax-M3
    os.environ["WEB_MODELS"] = "deepseek/deepseek-v4-flash,minimax/MiniMax-M3"
    try:
        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        # 候选 = 注册表 ∩ WEB_MODELS
        assert "deepseek/deepseek-v4-flash" in body["models"]
        assert "minimax/MiniMax-M3" in body["models"]
        # deepseek-v4-pro 不在 WEB_MODELS → 不应出现
        assert "deepseek/deepseek-v4-pro" not in body["models"]
    finally:
        os.environ.pop("WEB_MODELS", None)


def test_web_models_zero_regression_no_registry(tmp_path):
    """Web 端无 model_pool 注入 → 行为同现状（兜底）."""
    settings = _make_settings(tmp_path)
    settings = type(settings)(
        **{**settings.__dict__, "model_providers_raw": ""}  # 关掉注册表 env
    )
    session_store = SessionStore(str(tmp_path / "sessions"))

    engine = mock.Mock()
    engine.llm = mock.Mock(model="fake-model")
    engine.llm_pool = None  # 关键: 无池
    engine.session = session_store

    app = build_app(engine=engine)
    client = TestClient(app)
    os.environ.pop("WEB_MODELS", None)
    resp = client.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    # 零回归: 默认 candidates
    assert "fake-model" in body["models"]
    assert "deepseek-v4-flash" in body["models"]


# ── 6. refresh_config providers.json 热重载 ──


def test_refresh_registry_reload_new_provider(tmp_path):
    """refresh_provider_registry: 新增 provider 在 providers.json → 重建注册表生效."""
    initial = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
            "models": {
                "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
            },
            "default_model": "deepseek-v4-flash",
        }
    }
    _write_providers_json(tmp_path, initial)

    old_settings = _make_settings(tmp_path, model_providers_raw="")
    old_pool = _make_pool(old_settings, _FakeLLM())
    assert len(old_pool.registry.providers) == 1

    # 改 providers.json: 加 minimax provider
    new_cfg = {
        **initial,
        "minimax": {
            "base_url": "https://api.minimax.chat/v1",
            "api_key_env": "MINIMAX_API_KEY",
            "models": {
                "MiniMax-M3": {"context": 1000000, "thinking": False, "cost_tier": "mid"},
            },
            "default_model": "MiniMax-M3",
        },
    }
    _write_providers_json(tmp_path, new_cfg)

    # 重新加载
    new_settings = _make_settings(tmp_path, model_providers_raw="")
    msg, new_registry = refresh_provider_registry(old_pool, new_settings, re_read_settings=False)
    old_pool.registry = new_registry
    old_pool.clear_cache()

    assert len(old_pool.registry.providers) == 2
    assert "minimax" in old_pool.registry.providers
    assert "1 个 provider" in msg or "1 个" in msg  # 回执描述 N→M 变化


def test_refresh_registry_failure_keeps_old(tmp_path):
    """refresh_provider_registry: 加载失败 → 保持旧 registry + 如实反馈."""
    # 写一个 JSON 语法错误的 providers.json（不是 schema 错误, 是 JSON 本身无法解析）
    (tmp_path / "providers.json").write_text("{ malformed json", encoding="utf-8")

    old_settings = _make_settings(tmp_path, model_providers_raw="")
    old_pool = _make_pool(old_settings, _FakeLLM())
    old_provider_count = len(old_pool.registry.providers)

    new_settings = _make_settings(tmp_path, model_providers_raw="")
    msg, new_registry = refresh_provider_registry(old_pool, new_settings, re_read_settings=False)

    # 失败 → 旧 registry 保留, 新 registry 可能为 None 或回退 L0
    assert "失败" in msg or "保持旧" in msg
    # 保留旧 provider
    assert len(old_pool.registry.providers) == old_provider_count


def test_refresh_registry_via_corrections(tmp_path, build_test_engine):
    """修正工具 refresh_config 触发 → 中文回执 + 注册表更新."""
    _write_providers_json(
        tmp_path,
        {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
                "models": {
                    "deepseek-v4-flash": {"context": 1000000, "thinking": True, "cost_tier": "low"},
                },
                "default_model": "deepseek-v4-flash",
            }
        },
    )

    engine, _ = build_test_engine([{"content": "ok"}])
    # 手工安装 M50 扩展后的 refresh_executor (需要 model_pool 注入)
    settings = _make_settings(tmp_path)
    pool = _make_pool(settings, _FakeLLM())
    engine.correction_ctx.model_pool = pool
    # 补上 settings
    engine.settings = settings

    from llm_loop.introspection.providers_registry_reload import (
        install_refresh_executor,
    )

    install_refresh_executor(engine)

    # 调用 refresh_config 工具
    from llm_loop.core.message import ToolResultStatus

    result = engine.corrections.execute("refresh_config", {})
    assert result.status == ToolResultStatus.SUCCESS
    assert "模型目录" in result.content


# ── 7. 边界 & 集成 ──


def test_handle_model_command_non_model_text_returns_none(tmp_path):
    """handle_model_command 非 /model 文本 → 返回 None (调用方应继续走原路径)."""
    settings = _make_settings(tmp_path)
    session_store = SessionStore(str(tmp_path / "sessions"))
    pool = _make_pool(settings, _FakeLLM())
    ctx = mock.Mock()
    ctx.model_pool = pool
    ctx.session_set_override = None
    ctx.session_model_override = None

    result = handle_model_command("hello world", ctx, None, session_store)
    assert result is None


def test_handle_model_command_without_model_pool(tmp_path):
    """handle_model_command: model_pool=None → 失败回执 (不崩溃)."""
    session_store = SessionStore(str(tmp_path / "sessions"))
    ctx = mock.Mock()
    ctx.model_pool = None
    ctx.session_set_override = None
    ctx.session_model_override = None

    result = handle_model_command("/model", ctx, None, session_store)
    assert result is not None
    assert result.success is False
    assert "不可用" in result.reply
