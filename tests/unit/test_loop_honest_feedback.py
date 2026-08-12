"""M56 如实反馈/程序最小化收敛 测试（ANALYSIS-20260811-loop-strategy-branch-inventory）.

覆盖:
- C1: 初始会话持久化失败 → 注入 [程序异常]（不静默）
- C3: 压缩另存失败 → 注入 [程序异常] 到会话（AI 可感知）
- B5: architecture_status snapshot 的 context_usage.model_window（注入 fn 可见）
- RULE-AI-10 收敛: _check_loop_signals 统一入口存在且不改变既有检查行为
"""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import Message, MessageSource


def test_c1_initial_session_save_failure_injects_feedback(build_test_engine, fake_settings):
    """会话初始持久化失败 → 如实注入 [程序异常]，不静默（PREFERENCE_1）."""
    from llm_loop.core.session import SessionStore

    engine, fake = build_test_engine([{"content": "ok"}])
    original_save = SessionStore.save

    def _boom_first(session):
        # 仅首次（初始保存）失败；后续保存正常，便于验证注入内容已持久化
        if getattr(_boom_first, "count", 0) == 0:
            _boom_first.count = 1
            raise OSError("disk full")
        return original_save(engine.session, session)

    with mock.patch.object(engine.session, "save", side_effect=_boom_first):
        result = engine.run("fresh-session", "hello")

    # run 本身不崩（fail-open），会话中注入如实提示
    sess = engine.session.load(result.session_id)
    texts = [m.content for m in sess.messages]
    assert any("[程序异常]" in t and "session_persistence" in t for t in texts), texts


def test_c3_archive_sink_failure_injects_feedback(build_test_engine, fake_settings):
    """压缩另存失败 → 如实注入 [程序异常] 到会话（AI 可感知，不静默）."""
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    if engine.archive is None:
        return  # archive 未装配时无可测路径（行为不变）

    msg = Message(role="user", content="将被压缩的消息", source=MessageSource.USER)
    with mock.patch.object(engine.archive, "archive", side_effect=OSError("archive fail")):
        engine._archive_sink(sid, msg)

    sess = engine.session.load(sid)
    texts = [m.content for m in sess.messages]
    assert any("[程序异常]" in t and "archive_sink" in t for t in texts), texts


def test_b5_model_window_in_status_snapshot():
    """architecture_status snapshot 支持注入模型窗口查询（B5；未注入向后兼容 None）."""
    from llm_loop.introspection.status import ArchitectureStatusProvider

    status = ArchitectureStatusProvider(audit_dir=None, enabled=True)
    snap = status.snapshot()
    assert snap["context_usage"]["model_window"] is None  # 未注入 → None

    status.set_model_context_fn(lambda: {"label": "deepseek/deepseek-v4-flash", "context": 131072})
    snap = status.snapshot()
    assert snap["context_usage"]["model_window"] == {
        "label": "deepseek/deepseek-v4-flash",
        "context": 131072,
    }


def test_check_loop_signals_unified_entry(build_test_engine, fake_settings):
    """_check_loop_signals 统一入口存在，且逐个委托既有检测（行为不变）."""
    engine, fake = build_test_engine([])
    assert hasattr(engine, "_check_loop_signals")
    with mock.patch.object(
        engine, "_check_eval_trigger", wraps=engine._check_eval_trigger
    ) as eval_spy, mock.patch.object(
        engine, "_check_evolution_executing", wraps=engine._check_evolution_executing
    ) as evo_spy, mock.patch.object(
        engine, "_check_pending_review", wraps=engine._check_pending_review
    ) as review_spy:
        sess = engine.session.load(engine.session.create())
        engine._check_loop_signals(sess, rounds=1)
        eval_spy.assert_called_once()
        evo_spy.assert_called_once()
        review_spy.assert_called_once()
