"""M51 回复模型归因测试（founder 2026-08-11 需求: 回复下方标注实际模型）.

覆盖:
- 默认装配路径: 有 pool → 全限定 provider/model; 无 pool → 裸模型名
- client 无 model 属性（测试 stub）→ 空标签（不伪造）
- 会话级 override → override 全限定 ref
- per-call override → 解析后的全限定 ref
- fallback 降级成功 → 降级后的模型 ref（如实）
- 飞书端回复文本带 footer
- Web 端 ChatResponse 携带 model_used

全部 Mock/FakeLLM, 零真实网络。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from llm_loop.config import Settings
from llm_loop.core.session import SessionStore
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMHTTPError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry

# ── 辅助: 带 model 属性的 LLM 桩 ──


class _FakeLLMClient:
    """可编程 LLMClient 桩（具备 model 属性, duck typing LLMClient 协议）."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True
        self.max_tokens: int | None = None  # 2026-08-15 对齐 LLMClient 新装配字段
        self._responses: list[Any] = []
        self.calls: list[dict[str, Any]] = []

    def queue(self, responses: list[Any]) -> None:
        self._responses = list(responses)

    def chat(self, messages: list[dict], tools: list[dict], **kwargs: Any) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        item = self._responses.pop(0) if self._responses else LLMResponse(
            content="默认回答", tool_calls=[], provider="fake"
        )
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        pass


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


def _settings(tmp_path, **overrides) -> Settings:
    base: dict[str, Any] = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_model": "deepseek-v4-flash",
        "data_dir": str(tmp_path / "data"),
        "model_providers_raw": _TWO_PROVIDER_JSON,
        "model_fallbacks_raw": "",
    }
    base.update(overrides)
    return Settings(**base)


def _make_engine(tmp_path, pool, settings):
    """装配最小 LoopEngine（pool 由调用方注入以控制 client）."""
    from llm_loop.core.loop import LoopEngine
    from llm_loop.core.session import SessionStore
    from llm_loop.feedback.validator import DeclarationValidator
    from llm_loop.introspection.status import ArchitectureStatusProvider
    from llm_loop.memory.archive import ArchiveStore
    from llm_loop.memory.store import MemoryStore
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
    from llm_loop.tools.builtin.read_file import ReadFileTool
    from llm_loop.tools.registry import ToolRegistry

    memory = MemoryStore(settings.memory_dir)
    session = SessionStore(settings.sessions_dir)
    archive = ArchiveStore(settings.archive_dir) if settings.archive_enabled else None
    tool_registry = ToolRegistry(
        tool_timeout_s=settings.tool_timeout_s,
        max_output_chars=settings.tool_max_output_chars,
        archive_store=archive,
    )
    tool_registry.register(ReadFileTool())
    tool_registry.register(ExecuteCommandTool())
    status = ArchitectureStatusProvider(
        audit_dir=settings.audit_dir,
        enabled=settings.self_inspection_enabled,
        config_status=settings.to_status_dict,
    )
    ctx_corr = CorrectionContext()
    corrections = CorrectionToolRegistry(
        ctx_corr, audit_dir=str(tmp_path / "audit"), status_provider=status, archive_store=archive
    )
    ctx_corr.model_pool = pool
    validator = DeclarationValidator(audit_dir=settings.audit_dir)
    engine = LoopEngine(
        llm_client=pool.default_client,  # type: ignore[arg-type]
        registry=tool_registry,
        memory=memory,
        session=session,
        settings=settings,
        validator=validator,
        status_provider=status,
        correction_registry=corrections,
        correction_ctx=ctx_corr,
        archive=archive,
        llm_pool=pool,
    )
    return engine


def _make_pool(settings, default_client, cached: dict[str, Any] | None = None):
    pool = ModelClientPool(
        registry=load_registry(settings),
        default_client=default_client,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    # 预置 provider 缓存 → 路由返回 fake client, 零真实网络
    for pid, client in (cached or {}).items():
        pool._provider_cache[pid] = client  # noqa: SLF001
    return pool


# ── 默认路径 ──


def test_default_path_label_with_pool(build_test_engine) -> None:
    """默认装配 + pool → model_used 为注册表全限定标签."""
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"  # 与 conftest fake_settings.llm_model 对齐
    result = engine.run(engine.session.create(), "你好")
    # fake_settings.llm_base_url = fake.local → L0 合成 provider id = "default"
    assert result.model_used == "default/fake-model"


def test_default_path_label_no_pool(build_test_engine) -> None:
    """无 pool → 回退裸模型名（零回归）."""
    engine, fake = build_test_engine([{"content": "你好"}])
    fake.model = "fake-model"
    engine.llm_pool = None
    result = engine.run(engine.session.create(), "你好")
    assert result.model_used == "fake-model"


def test_client_without_model_attr_no_label(build_test_engine) -> None:
    """client 无 model 属性（conftest FakeLLM）→ 空标签, 不伪造."""
    engine, _fake = build_test_engine([{"content": "你好"}])
    result = engine.run(engine.session.create(), "你好")
    assert result.model_used == ""


# ── override 路径 ──


def test_session_override_label(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """会话级 override → model_used 为 override 全限定 ref."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    minimax_fake = _FakeLLMClient("MiniMax-M3")
    pool = _make_pool(settings, default_fake, cached={"minimax": minimax_fake})
    engine = _make_engine(tmp_path, pool, settings)

    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.model_override = "minimax/MiniMax-M3"
    engine.session.save(sess)

    result = engine.run(sid, "你好")
    assert result.model_used == "minimax/MiniMax-M3"


def test_per_call_override_label(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """per-call override (Web 下拉) → model_used 为解析后的全限定 ref."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    pro_fake = _FakeLLMClient("deepseek-v4-pro")
    pool = _make_pool(settings, default_fake, cached={"deepseek": pro_fake})
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好", model="deepseek/deepseek-v4-pro")
    assert result.model_used == "deepseek/deepseek-v4-pro"


# ── fallback 路径 ──


def test_fallback_success_label_is_fallback_model(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认模型 429 → 降级成功 → model_used 如实标注为降级后模型."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    settings = _settings(
        tmp_path, model_fallbacks_raw="minimax/MiniMax-M3"
    )
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    default_fake.queue(
        [LLMHTTPError("HTTP 429: rate limit", status_code=429, body="", provider="deepseek")]
    )
    fallback_fake = _FakeLLMClient("MiniMax-M3")
    fallback_fake.queue([LLMResponse(content="降级回答", tool_calls=[], provider="minimax")])
    pool = _make_pool(settings, default_fake, cached={"minimax": fallback_fake})
    engine = _make_engine(tmp_path, pool, settings)

    result = engine.run(engine.session.create(), "你好")
    assert result.final_answer == "降级回答"
    assert result.model_used == "minimax/MiniMax-M3"


# ── 飞书端 footer ──


def test_feishu_reply_has_model_footer(tmp_path) -> None:
    """飞书文本回复末尾带模型 footer."""
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    session_store = SessionStore(str(tmp_path / "sessions"))

    class _StubEngine:
        session = session_store

        def run(self, sid, text):
            return SimpleNamespace(
                session_id=sid,
                final_answer="模型回答",
                verification_note=None,
                rounds=1,
                tool_calls=[],
                truncated=False,
                model_used="deepseek/deepseek-v4-flash",
            )

    session_map = SessionMap(session_store, path=str(tmp_path / "map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        _StubEngine(),
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    msg = FeishuMessage(
        message_id="om_1", sender_id="ou_user", chat_id="oc_chat", msg_type="text", text="你好"
    )
    handler.handle(msg)

    assert len(replies) == 1
    assert replies[0][1].startswith("模型回答")
    assert replies[0][1].endswith("—— deepseek/deepseek-v4-flash")


def test_feishu_reply_no_footer_when_label_empty(tmp_path) -> None:
    """model_used 为空 → 不加 footer（不伪造标签）."""
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    session_store = SessionStore(str(tmp_path / "sessions"))

    class _StubEngine:
        session = session_store

        def run(self, sid, text):
            return SimpleNamespace(
                session_id=sid,
                final_answer="模型回答",
                verification_note=None,
                rounds=1,
                tool_calls=[],
                truncated=False,
                model_used="",
            )

    session_map = SessionMap(session_store, path=str(tmp_path / "map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        _StubEngine(),
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    msg = FeishuMessage(
        message_id="om_2", sender_id="ou_user", chat_id="oc_chat", msg_type="text", text="你好"
    )
    handler.handle(msg)

    assert replies[0][1] == "模型回答"


# ── Web 端 ──


def test_web_chat_response_carries_model_used(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/v1/chat 响应含 model_used 字段."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    from fastapi.testclient import TestClient

    from llm_loop.web import build_app

    settings = _settings(tmp_path)
    default_fake = _FakeLLMClient("deepseek-v4-flash")
    pool = _make_pool(settings, default_fake)
    engine = _make_engine(tmp_path, pool, settings)

    client = TestClient(build_app(engine=engine))
    resp = client.post("/api/v1/chat", json={"message": "你好"})
    assert resp.status_code == 200
    assert resp.json()["model_used"] == "deepseek/deepseek-v4-flash"


# ── M55: 飞书 /new 会话指令 ──


def test_feishu_new_command_creates_fresh_session(tmp_path) -> None:
    """飞书 /new → 换新会话 + 如实回执 + 旧会话保留."""
    from llm_loop.core.session import SessionStore
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
    from llm_loop.feishu.session_map import SessionMap

    session_store = SessionStore(str(tmp_path / "sessions"))

    class _StubEngine:
        session = session_store

        def run(self, sid, text):
            return SimpleNamespace(
                session_id=sid, final_answer="回答", verification_note=None,
                rounds=1, tool_calls=[], truncated=False, model_used="",
                tokens_in=0, tokens_out=0,
            )

    session_map = SessionMap(session_store, path=str(tmp_path / "map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        _StubEngine(), session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    msg = FeishuMessage(
        message_id="om_n1", sender_id="ou_u", chat_id="oc_c", msg_type="text", text="/new"
    )
    key = session_map.p2p_key("ou_u")

    old_sid = session_map.get_or_create(key)  # 模拟已有会话
    handler.handle(msg)
    new_sid = session_map.get(key)

    assert new_sid != old_sid  # 换了新会话
    assert "已新建会话" in replies[0][1]
    assert session_store.exists(old_sid)  # 旧会话保留
