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
_EXPLICIT_MODEL = "glm/glm-5.3"
_OTHER_EXPLICIT_MODEL = "cognilocal/qwen3.8-flash-next"


class _Registry:
    _KNOWN = {
        _EXPLICIT_MODEL: ("glm", "glm-5.3"),
        _OTHER_EXPLICIT_MODEL: ("cognilocal", "qwen3.8-flash-next"),
    }

    def resolve(self, model: str) -> tuple[str, str]:
        try:
            return self._KNOWN[model]
        except KeyError as exc:
            raise ValueError(model) from exc


class _Pool:
    def __init__(self) -> None:
        self.registry = _Registry()

    def registry_snapshot(self) -> _Registry:
        return self.registry


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
        history_compacted=False,
        provider_output_truncated=False,
        run_incomplete=False,
        projection_validator_failed=False,
        projection_rebuilt=False,
        projection_cannot_fit=False,
    )


def _engine(store: SessionStore, captured: list[str]) -> mock.Mock:
    """最小 Mock engine：workspace CM + run 捕获 session_id."""
    engine = mock.Mock()
    engine.llm = mock.Mock(model="fake-model")
    engine.llm_pool = None
    engine.settings = mock.Mock(history_max_chars=10000)
    engine.workspace_root = ""  # attachment scope fallback uses cwd; keep Mock from fabricating a path
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


def test_chat_new_session_explicit_model_wins_at_creation_over_shared_current(tmp_path):
    """新会话显式模型是创建 authority，不得先继承另一 tab/shared-current 模型。"""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)
    engine = _engine(store, captured)
    engine.llm_pool = _Pool()

    client = TestClient(build_app(engine=engine))
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hi", "new_session": True, "model": _EXPLICIT_MODEL},
    )
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(old_sid).model_override == _INHERIT_MODEL
    assert store.load(new_sid).model_override == _EXPLICIT_MODEL
    assert captured == [new_sid]


def test_chat_new_session_explicit_qwen_wins_over_shared_glm(tmp_path):
    """反向并发 tab 场景也必须由本请求显式模型决定新会话初始 authority。"""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_EXPLICIT_MODEL)
    store.set_shared_current(old_sid)
    engine = _engine(store, captured)
    engine.llm_pool = _Pool()

    client = TestClient(build_app(engine=engine))
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hi", "new_session": True, "model": _OTHER_EXPLICIT_MODEL},
    )
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(old_sid).model_override == _EXPLICIT_MODEL
    assert store.load(new_sid).model_override == _OTHER_EXPLICIT_MODEL


def test_chat_new_session_invalid_explicit_model_does_not_inherit_shared_authority(tmp_path):
    """显式但不可解析的模型走 per-call unavailable；不得静默继承别的会话 authority。"""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)
    engine = _engine(store, captured)
    engine.llm_pool = _Pool()

    client = TestClient(build_app(engine=engine))
    resp = client.post(
        "/api/v1/chat",
        json={"message": "hi", "new_session": True, "model": "unknown/not-registered"},
    )
    assert resp.status_code == 200, resp.text

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(old_sid).model_override == _INHERIT_MODEL
    assert store.load(new_sid).model_override is None


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
    with open(store._path(old_sid), "w", encoding="utf-8") as f:  # noqa: SLF001
        f.write("{broken")

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


def test_chat_stream_new_session_explicit_model_wins_at_creation(tmp_path):
    """流式端点同样必须让本请求显式模型直接成为新会话创建 authority。"""
    store, captured = _setup(tmp_path)
    old_sid = store.create(model_override=_INHERIT_MODEL)
    store.set_shared_current(old_sid)
    engine = _engine(store, captured)
    engine.llm_pool = _Pool()

    client = TestClient(build_app(engine=engine))
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "hi", "new_session": True, "model": _EXPLICIT_MODEL},
    ) as resp:
        assert resp.status_code == 200, resp.text
        list(resp.iter_text())

    new_sid = store.get_shared_current()
    assert new_sid is not None and new_sid != old_sid
    assert store.load(old_sid).model_override == _INHERIT_MODEL
    assert store.load(new_sid).model_override == _EXPLICIT_MODEL
    assert captured == [new_sid]
