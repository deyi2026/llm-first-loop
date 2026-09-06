"""P1-A TaskAuth semantic-classifier retirement regression.

The runtime owns provenance and mechanical Task state.  It must not turn user prose
such as "继续/重做" into a second authorization token.  A completed Task can still be
reopened, but only through the model-visible explicit ``confirm=true`` action bit; the
model decides whether the current genuine user instruction authorizes that action.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import llm_loop.introspection.tools_task as tt
from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore
from llm_loop.introspection.tools_task import TASK_UPDATE_TOOL_DEF


def _setup_goal_task():
    d = tempfile.mkdtemp()
    g = GoalStore(d).create("目标T")
    store = TaskStore(d)
    t = store.create(g.id, "任务", acceptance=["可验收"])
    store.update(g.id, t.task_id, status="in_progress")
    store.update(g.id, t.task_id, status="done")
    return d, g.id, t.task_id


def _host(audit_dir: str, **settings):
    return SimpleNamespace(
        settings=SimpleNamespace(audit_dir=audit_dir, **settings),
        audit_dir=audit_dir,
    )


def test_task_update_schema_exposes_explicit_reopen_confirm():
    props = TASK_UPDATE_TOOL_DEF["parameters"]["properties"]
    assert props["confirm"]["type"] == "boolean"
    text = TASK_UPDATE_TOOL_DEF["description"] + props["confirm"]["description"]
    assert "模型" in text and "当前" in text and "confirm=true" in text
    assert "程序态授权" not in text


def test_done_reopen_without_confirm_is_mechanically_rejected():
    d, gid, tid = _setup_goal_task()
    r = tt.run_task_update(
        None,
        _host(d),
        {"goal_id": gid, "task_id": tid, "status": "in_progress"},
    )
    assert r.status == ToolResultStatus.FAILURE
    assert "confirm=true" in r.content
    assert TaskStore(d).get(gid, tid).status == "done"


def test_done_reopen_with_model_confirm_succeeds_without_program_auth_context():
    d, gid, tid = _setup_goal_task()
    # A stale legacy-looking setting must have no semantic authority after P1-A.
    host = _host(d, task_auth_context_mode="enforce")
    r = tt.run_task_update(
        None,
        host,
        {"goal_id": gid, "task_id": tid, "status": "in_progress", "confirm": True},
    )
    assert r.status == ToolResultStatus.SUCCESS
    assert TaskStore(d).get(gid, tid).status == "in_progress"


def test_task_store_confirm_is_not_a_program_generated_authorization_token():
    d, gid, tid = _setup_goal_task()
    store = TaskStore(d)
    try:
        store.update(gid, tid, status="in_progress")
    except ValueError as exc:
        assert "程序不解析用户措辞" in str(exc)
    else:  # pragma: no cover - hard regression signal
        raise AssertionError("done→reopen must require explicit confirm")
    reopened = store.update(gid, tid, status="in_progress", confirm=True)
    assert reopened.status == "in_progress"


def test_task_auth_semantic_module_and_runtime_setting_are_retired(fake_settings):
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/core/loop/authorization_context.py").exists()
    assert not hasattr(fake_settings, "task_auth_context_mode")
    assert "task_auth_context_mode" not in fake_settings.to_status_dict()


def test_current_user_words_do_not_emit_task_auth_events(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}, {"content": "ok"}])
    sid = engine.session.create()
    calls: list[tuple[str, str, str]] = []
    original = engine._record_action

    def _record(phase: str, action_type: str, detail: str) -> None:
        calls.append((str(phase), str(action_type), str(detail)))
        original(phase, action_type, detail)

    engine._record_action = _record  # type: ignore[method-assign]
    engine.run(sid, "继续")
    engine.run(sid, "重做一下那个任务")

    assert not [row for row in calls if row[0].startswith("task_auth")]
