"""CLI adapters against native runner/store contracts; no live providers."""
from __future__ import annotations

import io
import json
import threading
import time
from types import SimpleNamespace

import pytest

import llm_loop.cli as cli
from llm_loop.core.loop import LoopResult
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.llm.client import StreamDelta, ToolRoundInfo
from llm_loop.terminal.execution import _pump, run_turn
from llm_loop.terminal.presentation import Presenter, safe_text
from llm_loop.terminal.queries import dispatch_query
from llm_loop.terminal.records import export_record, read_session
from llm_loop.terminal.settings import ACTIONS, UISettings, load_ui, save_ui, validate_ui


def test_terminal_controls_are_inert_but_json_is_exact(capsys):
    content = "中文\x1b]52;c;secret\x07\x1b[2J\rnext\n"
    assert "\x1b" not in safe_text(content)
    view = Presenter("json")
    view.started("s", "g")
    view.delta(StreamDelta(text=content))
    view.finish(LoopResult("s", content))
    assert json.loads(capsys.readouterr().out)["final_answer"] == content


def test_text_deltas_are_immediate_and_final_is_not_duplicated(capsys):
    view = Presenter()
    view.started("s", "g")
    view.delta(StreamDelta(text="first "))
    assert capsys.readouterr().out == "first "
    view.delta(StreamDelta(text="second"))
    view.finish(LoopResult("s", "first second"))
    assert capsys.readouterr().out == "second\n"


def test_jsonl_monotonic_protocol_and_authoritative_incomplete(capsys):
    view = Presenter("jsonl")
    view.started("s", "g")
    view.delta(StreamDelta(text="part", tool_round=ToolRoundInfo("exec", 1, "PRIVATE ARG", "call-1")))
    assert view.finish(LoopResult("s", "part", run_incomplete=True)) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["seq"] for row in lines] == list(range(1, len(lines) + 1))
    assert [row["type"] for row in lines] == ["run_started", "text_delta", "tool_started", "result"]
    assert all(row["run_generation"] == "g" for row in lines)
    assert "PRIVATE ARG" not in json.dumps(lines)
    assert lines[-1]["status"] == "incomplete"


def test_native_background_runner_streams_and_settles(capsys):
    seen = []

    class Engine:
        runner: BackgroundRunner

        def run_stream(self, sid, text, model, **kwargs):
            seen.append((sid, text, kwargs.get("ingress")))
            yield StreamDelta(text="live")
            return LoopResult(sid, "live", model_used="fixture/model")

    engine = Engine()
    engine.runner = BackgroundRunner(engine)
    assert run_turn(engine, "owned", "exact\nmessage", Presenter("jsonl")) == 0
    assert seen[0][:2] == ("owned", "exact\nmessage")
    assert seen[0][2] is not None
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0]["run_generation"]
    assert rows[-1]["type"] == "result"
    assert not engine.runner.is_running("owned")


def test_cancel_is_bound_to_owned_generation_and_waits_for_native_terminal(capsys):
    class Engine:
        runner: BackgroundRunner

        def run_stream(self, sid, text, model, **kwargs):
            while not self.runner.is_cancelled(sid):
                time.sleep(0.005)
            yield StreamDelta(text="partial")
            return LoopResult(sid, "partial", run_incomplete=True, cancel_reason="user_stop")

    engine = Engine()
    engine.runner = BackgroundRunner(engine)
    handle, events = engine.runner.start("owned", "hello")
    assert handle is not None and events is not None
    assert engine.runner.cancel("owned", expected_run_generation="stale") is False
    view = Presenter("jsonl")
    view.started("owned", handle.run_generation)
    interrupt = threading.Event()
    interrupt.set()
    assert _pump(engine.runner, handle, events, view, interrupt, None) == 1
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[1]["type"] == "cancel_requested" and rows[1]["accepted"]
    assert rows[-1]["cancel_reason"] == "user_stop"
    engine.runner.unsubscribe("owned", events)


@pytest.fixture
def query_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "query-data"))
    monkeypatch.setenv("LFL_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("MODEL_PROVIDERS", json.dumps({
        "fixture": {"base_url": "https://invalid.example", "api_key_env": "SECRET_KEY",
                    "models": {"model": {"context": 8192}}}
    }))
    monkeypatch.setenv("LLM_API_KEY", "PRIVATE_MUST_NOT_PRINT")
    monkeypatch.setenv("LLM_BASE_URL", "https://private:secret@invalid.example?token=private")
    monkeypatch.setattr("llm_loop.factory.build_engine", lambda *a, **k: pytest.fail("read-only must not build Engine"))
    monkeypatch.setattr(cli, "_prepare_cli_process", lambda: pytest.fail("read-only must not bootstrap"))
    return tmp_path


@pytest.mark.parametrize("argv", [
    ["help"], ["keys"], ["models", "--json"], ["identity", "--json"],
    ["config", "show", "--json"], ["sessions", "list", "--json"], ["list"],
])
def test_queries_are_credential_free_and_do_not_create_data(query_env, capsys, argv):
    assert cli.main(argv) == 0
    output = capsys.readouterr().out
    assert "PRIVATE_MUST_NOT_PRINT" not in output
    assert "private:secret" not in output
    assert not (query_env / "query-data").exists()


def test_query_uses_selected_installed_data_and_workspace(query_env, capsys):
    options = SimpleNamespace(config=None, data_dir=str(query_env / "selected"),
                              workspace=str(query_env / "workspace"))
    assert dispatch_query(["identity", "--json"], options) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["data_dir"] == str(query_env / "selected")
    assert report["workspace"] == str(query_env / "workspace")
    assert report["actual_model"] is None


def test_integrated_help_keeps_existing_installer_and_extension_commands(capsys):
    assert cli.application_main(["--help"]) == 0
    help_text = capsys.readouterr().out
    for command in ("start [--plan]", "extensions", "upgrade --plan", "chat", "sessions"):
        assert command in help_text


def test_legacy_module_query_uses_installed_home_not_site_packages(query_env, monkeypatch, capsys):
    installed_home = query_env / "installed-state"
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("LFL_DATA_DIR", raising=False)
    monkeypatch.delenv("LFL_ENV_FILE", raising=False)
    monkeypatch.setattr(cli, "bundle_root", lambda: query_env / "fake-installed-bundle")
    monkeypatch.setattr(cli, "default_home", lambda: installed_home)
    assert cli.main(["identity", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data_dir"] == str(installed_home / "data")
    assert not installed_home.exists()


def test_exact_read_export_does_not_modify_source_or_overwrite(tmp_path):
    data = tmp_path / "data"
    (data / "sessions").mkdir(parents=True)
    content = "  中文\r\n" + "code\n" * 5000
    raw = {"session_id": "s", "messages": [{"role": "assistant", "content": content}]}
    source = data / "sessions/s.json"
    source.write_text(json.dumps(raw, ensure_ascii=False))
    before = source.read_bytes()
    read = read_session(data, "s")
    target = tmp_path / "export.json"
    export_record(read, target, "json")
    assert json.loads(target.read_text())["messages"][0]["content"] == content
    assert source.read_bytes() == before
    assert list(data.iterdir()) == [data / "sessions"]
    with pytest.raises(FileExistsError):
        export_record(read, target, "json")
    with pytest.raises(ValueError):
        read_session(data, "../s")


def test_missing_session_query_never_creates_replacement(query_env):
    assert cli.main(["sessions", "show", "missing"]) == 1
    assert not (query_env / "query-data").exists()


def test_user_ui_round_trip_atomic_and_no_policy_fields(tmp_path):
    target = tmp_path / "config/terminal.json"
    value = UISettings(theme="mono", multiline=True, keybindings={"view.tasks": []})
    save_ui(value, target)
    assert load_ui(target) == value
    assert list(target.parent.iterdir()) == [target]
    with pytest.raises(ValueError):
        validate_ui({"exec_mode": "full"})
    with pytest.raises(ValueError):
        validate_ui({"keybindings": {"view.tasks": ACTIONS["view.model"]}})
    with pytest.raises(ValueError):
        validate_ui({"keybindings": {"view.tasks": ["c-c"]}})


def test_structured_interactive_is_rejected_before_bootstrap(monkeypatch):
    class TTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(cli.sys, "stdin", TTY())
    monkeypatch.setattr(cli, "_prepare_cli_process", lambda: pytest.fail("must not bootstrap"))
    assert cli.main(["--interactive", "--output", "json"]) == 2


def test_workspace_queries_validate_native_partition_and_tombstone(tmp_path):
    from llm_loop.terminal.records import session_root, session_rows
    from llm_loop.workspace.store import WorkspaceStore

    data = tmp_path / "partitioned"
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    registry = WorkspaceStore(data)
    wa, wb = registry.register(str(a)), registry.register(str(b))
    root_a, root_b = data / "sessions" / wa.id, data / "sessions" / wb.id
    root_a.mkdir(parents=True)
    root_b.mkdir()
    raw = {"session_id": "s", "title": "owned-a", "messages": []}
    (root_a / "s.json").write_text(json.dumps(raw))
    identities = data / "sessions/.identity"
    identities.mkdir()
    identity = identities / "s.json"
    identity.write_text(json.dumps({"owner": wa.id}))
    before = {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()}
    assert session_root(data, a) == root_a
    assert read_session(data, "s", root=root_a)["title"] == "owned-a"
    assert session_rows(data, root=root_b) == []
    with pytest.raises((ValueError, FileNotFoundError)):
        read_session(data, "s", root=root_b)
    after = {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()}
    assert after == before
    identity.write_text(json.dumps({"owner": wa.id, "deleted_at": "deleted"}))
    with pytest.raises(ValueError, match="deleted"):
        read_session(data, "s", root=root_a)


def test_event_log_query_uses_native_replay_with_no_snapshot_write(tmp_path):
    from llm_loop.event_log.store import EventStore

    data = tmp_path / "event-source"
    identity = data / "sessions/.identity"
    identity.mkdir(parents=True)
    (identity / "s.json").write_text(json.dumps({"owner": "."}))
    store = EventStore(data / "event_logs")
    assert store.append("s", "session.created", {"session_id": "s", "title": "events"}) is not None
    before = {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()}
    raw = read_session(data, "s", "event_log")
    assert raw["session_id"] == "s"
    assert raw["title"] == "events"
    after = {p.relative_to(data): p.read_bytes() for p in data.rglob("*") if p.is_file()}
    assert after == before
    assert not (data / "sessions/s.json").exists()


def test_tasks_view_uses_real_goal_identity_and_no_cross_session(tmp_path):
    from llm_loop.introspection.goal import GoalStore
    from llm_loop.introspection.task_store import TaskStore
    from llm_loop.terminal.shell import task_snapshot

    audit = tmp_path / "audit"
    goal = GoalStore(audit).create("fixture objective", session_id="owned")
    task = TaskStore(audit).create(goal.id, "fixture task", acceptance=["fixture observed"])
    engine = SimpleNamespace(settings=SimpleNamespace(audit_dir=audit))
    report = task_snapshot(engine, "owned")
    assert report["goal"]["id"] == goal.id
    assert report["tasks"][0]["task_id"] == task.task_id
    other = task_snapshot(engine, "other")
    assert other["goal"] is None and other["tasks"] == []


def test_sigterm_result_and_process_status_agree(capsys):
    import queue

    cancelled = []
    runner = SimpleNamespace(cancel=lambda sid, **kwargs: cancelled.append((sid, kwargs)) or True)
    handle = SimpleNamespace(session_id="s", run_generation="owned-generation")
    events = queue.Queue()
    events.put({"type": "done", "result": LoopResult("s", "partial", cancel_reason="user_stop")})
    interrupt, terminated = threading.Event(), threading.Event()
    interrupt.set()
    terminated.set()
    view = Presenter("jsonl")
    view.started("s", "owned-generation")
    assert _pump(runner, handle, events, view, interrupt, None, terminated) == 143
    assert cancelled == [("s", {"expected_run_generation": "owned-generation"})]
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1]["exit_code"] == 143
