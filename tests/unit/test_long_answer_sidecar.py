"""Long-answer正文sidecar必须精确归属session并随物理删除清理。"""

from pathlib import Path

from llm_loop.core.session import Session


def _long_root(engine) -> Path:
    return Path(engine.settings.data_dir) / "audit" / "long_answers"


def test_long_answer_uses_full_session_directory(build_test_engine):
    engine, _ = build_test_engine([])
    sid = "12345678-session-A"
    engine.session.save(Session(session_id=sid))
    answer = "LONG-ANSWER-CONTENT" * 1000

    engine._persist_long_answer(sid, answer)

    session_dir = _long_root(engine) / sid
    files = list(session_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == answer
    assert not list(_long_root(engine).glob(f"{sid[:8]}-*.md"))


def test_physical_delete_removes_exact_long_answer_dir_only(fake_settings, monkeypatch):
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    engine = build_engine(fake_settings)
    sid = "12345678-session-A"
    neighbor = "12345678-session-B"
    engine.session.save(Session(session_id=sid))
    engine.session.save(Session(session_id=neighbor))

    engine._persist_long_answer(sid, "A" * 12000)
    engine._persist_long_answer(neighbor, "B" * 12000)
    session_dir = _long_root(engine) / sid
    neighbor_dir = _long_root(engine) / neighbor
    assert list(session_dir.glob("*.md"))
    assert list(neighbor_dir.glob("*.md"))

    assert engine.session.delete(sid) is True

    assert not session_dir.exists()
    assert list(neighbor_dir.glob("*.md"))
    assert engine.session.exists(neighbor)
