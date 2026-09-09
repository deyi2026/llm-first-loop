"""M60: Web 端 new_session 新建会话继承旧共享会话 model_override（对齐 M52 三端语义）.

背景: 飞书 owner 私聊与 Web 跨端共享当前会话（shared_current）。Web
/api/v1/chat(new_session=true) 原先直接 create() → 新会话 model_override=None →
飞书侧经 get_shared_current 拉到该新会话后回落装配默认（用户实测"新建会话变成本
地模型"）。M60 起新建前继承旧共享会话 override（fail-open → None），与飞书
SessionMap.inherit_model_override（M52-fix）/ CLI /new 同语义。

全部 Mock 引擎 + 真实 SessionStore，零真实网络。
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from llm_loop.core.session import SessionStore
from llm_loop.web import build_app

_INHERIT_MODEL = "minimax/MiniMax-M3"


def _result_mock(sid: str) -> mock.Mock:
    """LoopResult 形状的最小 mock（ChatResponse 透传字段齐全）."""
    return mock.Mock(
        session_id=sid,
        final_answer="ok",
        verification_note=None,
        rounds=1,
        tool_calls=[],
        truncated=False,
        model_used=_INHERIT_MODEL,
        tokens_in=1,
        tokens_out=1,
        tokens_cache_hit=0,
        reasoning_content=None,
        reasoning_mode="auto",
        reasoning_capable=False,
        reasoning_control="legacy",
        reasoning_supported=False,
        reasoning_effective=False,
        reasoning_tokens=None,
    )


def _engine(store: SessionStore, captured: list[str]) -> mock.Mock:
    """最小 Mock engine：workspace CM + run 捕获 session_id."""
    engine = mock.Mock()
    engine.llm = mock.Mock(model="fake-model")
    engine.settings = mock.Mock(history_max_chars=10000)
    engine.workspace_root = (
        ""  # attachment scope fallback uses cwd; keep Mock from fabricating a path
    )
    engine.session = store
    engine.runner = None  # 流式走回退生成器直驱路径
    cm = mock.MagicMock()
    cm.__enter__.return_value = 0
    cm.__exit__.return_value = False
    engine.workspace_snapshot.return_value = cm

    def _run(session_id: str, message: str, **kwargs) -> mock.Mock:
        captured.append(session_id)
        return _result_mock(session_id)

    engine._run_with_acquired.side_effect = _run

    def _run_stream(session_id: str, message: str, **kwargs):
        captured.append(session_id)
        # 生成器：正常结束并把 LoopResult 形状结果经 StopIteration.value 返回
        yield mock.Mock(text="ok", reasoning="", tool_round=None)
        return _result_mock(session_id)

    engine._run_stream_with_acquired.side_effect = _run_stream
    return engine


def _setup(tmp_path: Path) -> tuple[SessionStore, list[str]]:
    store = SessionStore(str(tmp_path / "sessions"))
    return store, []


def test_chat_new_session_inherits_shared_model_override(tmp_path):
    """主场景: 旧共享会话带 override → new_session=true 新会话继承同一模型."""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)

    client = TestClient(build_app(engine=_engine(store, captured)))
    resp = client.post("/api/v1/chat", json={"message": "hi", "new_session": True})
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(new_sid).model_override == _INHERIT_MODEL
    assert captured == [new_sid]  # engine 实际执行在新会话上


def test_chat_new_session_no_shared_fail_open_none(tmp_path):
    """无共享会话 → 继承 fail-open 为 None（回落装配默认），新建不阻断."""
    store, captured = _setup(tmp_path)
    assert store.get_shared_current() is None

    client = TestClient(build_app(engine=_engine(store, captured)))
    resp = client.post("/api/v1/chat", json={"message": "hi", "new_session": True})
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None
    assert store.load(new_sid).model_override is None


def test_chat_new_session_corrupt_shared_fail_open_none(tmp_path):
    """共享指向已损坏会话 → fail-open None，不阻断新建（与 M52 fail-open 同语义）."""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)
    store._path(old_sid).write_text("{broken", encoding="utf-8")  # noqa: SLF001

    client = TestClient(build_app(engine=_engine(store, captured)))
    resp = client.post("/api/v1/chat", json={"message": "hi", "new_session": True})
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(new_sid).model_override is None


def test_chat_stream_new_session_inherits_shared_model_override(tmp_path):
    """流式端点同语义: new_session=true 新会话继承旧共享会话 override."""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)

    client = TestClient(build_app(engine=_engine(store, captured)))
    with client.stream(
        "POST", "/api/v1/chat/stream", json={"message": "hi", "new_session": True}
    ) as resp:
        assert resp.status_code == 200, resp.text
        list(resp.iter_text())

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(new_sid).model_override == _INHERIT_MODEL
    assert captured == [new_sid]
