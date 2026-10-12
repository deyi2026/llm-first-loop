"""M56 如实反馈/程序最小化收敛 测试（ANALYSIS-20260811-loop-strategy-branch-inventory）.

覆盖:
- C1: 初始会话持久化失败 → observability/recovery 保留，但不注入 prompt/history
- C3: 压缩另存失败 → selfheal/status 可查，但不注入 prompt/history
- B5: architecture_status snapshot 的 context_usage.model_window（注入 fn 可见）
- RULE-AI-10 Rule-first: 普通模型终止域不再承载周期维护 signal scanner
"""

from __future__ import annotations

from unittest import mock

from llm_loop.core.message import Message, MessageSource


def test_c1_initial_session_save_failure_is_observable_not_prompted(build_test_engine, fake_settings):
    """初始保存失败保留 selfheal/status 证据，但不写会话或 provider prompt."""
    import json

    from llm_loop.core.session import SessionStore

    engine, fake = build_test_engine([{"content": "ok"}])
    original_save = SessionStore.save

    def _boom_first(session):
        if getattr(_boom_first, "count", 0) == 0:
            _boom_first.count = 1
            raise OSError("disk full")
        return original_save(engine.session, session)

    with mock.patch.object(engine.session, "save", side_effect=_boom_first):
        result = engine.run("fresh-session", "hello")

    assert result.final_answer == "ok"
    sess = engine.session.load(result.session_id)
    assert not any("session_persistence" in m.content for m in sess.messages)
    wire = json.dumps(fake.calls[0]["messages"], ensure_ascii=False)
    assert "session_persistence" not in wire
    assert "[程序异常]" not in wire
    log = fake_settings.audit_dir / "selfheal_log.jsonl"
    assert '"component": "session_persistence"' in log.read_text(encoding="utf-8")


def test_c3_archive_sink_failure_is_observable_not_persisted(build_test_engine, fake_settings):
    """archive_sink 失败写 selfheal/status，但不创建会话级程序消息."""
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    if engine.archive is None:
        return

    msg = Message(role="user", content="将被压缩的消息", source=MessageSource.USER)
    with mock.patch.object(engine.archive, "archive", side_effect=OSError("archive fail")):
        engine._archive_sink(sid, msg)

    sess = engine.session.load(sid)
    assert not any("archive_sink" in m.content for m in sess.messages)
    log = fake_settings.audit_dir / "selfheal_log.jsonl"
    assert '"component": "archive_sink"' in log.read_text(encoding="utf-8")


def test_c3_archive_sink_failure_during_active_run_does_not_pollute_bound_session(
    build_test_engine, fake_settings
):
    """active run 的 archive fault 也只能进 observability，不能污染绑定 Session."""
    engine, _fake = build_test_engine([])
    sid = engine.session.create()
    if engine.archive is None:
        return

    active = engine.session.load(sid)
    token = None
    with engine.session.run_lease(sid) as acquired:
        assert acquired is True
        token = engine.session._activate_run_save_token(sid)  # noqa: SLF001 — 模拟lifecycle真实run边界
        try:
            from llm_loop.core.run_context import current_session_id

            engine.session._bind_run_save_token(active, token)  # noqa: SLF001
            with engine._run_state_mgr.guard:  # noqa: SLF001 — 与engine真实run绑定表一致（前会话重构: _run_states_guard → _run_state_mgr.guard）
                engine._run_sessions[sid] = active  # noqa: SLF001
            ctx_token = current_session_id.set(sid)
            try:
                msg = Message(role="user", content="active-run archive failure", source=MessageSource.USER)
                with mock.patch.object(engine.archive, "archive", side_effect=OSError("archive fail in run")):
                    engine._archive_sink(sid, msg)
            finally:
                current_session_id.reset(ctx_token)

            assert not any("archive_sink" in m.content for m in active.messages)
            # 活动对象仍可正常持久化；fault 证据走 selfheal/status，不写 history。
            engine.session.save(active)
        finally:
            with engine._run_state_mgr.guard:  # noqa: SLF001
                engine._run_sessions.pop(sid, None)  # noqa: SLF001
            if token is not None:
                engine.session._deactivate_run_save_token(sid, token)  # noqa: SLF001

    stored = engine.session.load(sid)
    assert not any("archive_sink" in m.content for m in stored.messages)
    log = fake_settings.audit_dir / "selfheal_log.jsonl"
    assert '"component": "archive_sink"' in log.read_text(encoding="utf-8")


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


def test_model_termination_controller_has_no_maintenance_signal_scanner(build_test_engine):
    """Rule-first: ordinary model loop has no periodic maintenance strategy scanner."""
    engine, _fake = build_test_engine([])
    assert not hasattr(engine._termination, "_check_loop_signals")
    assert not hasattr(engine._termination, "_check_eval_trigger")
    assert not hasattr(engine._termination, "_check_evolution_executing")
    assert not hasattr(engine._termination, "_check_pending_review")
