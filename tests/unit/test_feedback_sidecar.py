"""Feedback sidecar必须与会话物理删除共享精确归属与稳定锁。"""

import json
from pathlib import Path

import pytest

from llm_loop.feedback.honesty import append_feedback, delete_feedback_for_session


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_feedback_purge_is_exact(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(path, {"session_id": "session-A", "note": "alpha"})
    append_feedback(path, {"session_id": "session-B", "note": "beta"})

    assert delete_feedback_for_session(path, "session-A") == 1
    assert _records(path) == [{"session_id": "session-B", "note": "beta"}]


def test_feedback_purge_corrupt_line_fails_closed(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text('{"session_id":"session-A"}\n{broken\n', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="corrupt"):
        delete_feedback_for_session(path, "session-A")

    assert path.read_bytes() == before


def test_factory_delete_purges_only_target_feedback(fake_settings, monkeypatch):
    from llm_loop.core.interop_watch import InboxWatcher
    from llm_loop.factory import build_engine

    monkeypatch.setattr(InboxWatcher, "start", lambda self: None)
    engine = build_engine(fake_settings)
    sid = engine.session.create()
    neighbor = engine.session.create()
    path = Path(engine.settings.data_dir) / "feedback.jsonl"
    append_feedback(path, {"session_id": sid, "note": "target"})
    append_feedback(path, {"session_id": neighbor, "note": "keep"})

    assert engine.session.delete(sid) is True

    assert _records(path) == [{"session_id": neighbor, "note": "keep"}]
    assert engine.session.exists(neighbor)
