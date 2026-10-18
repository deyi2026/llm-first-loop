"""CLI adapters against native runner/store contracts; no live providers."""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
import time
import tracemalloc
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


def test_ten_thousand_stream_events_remain_ordered_lossless_and_bounded(monkeypatch):
    class StreamingSink:
        def __init__(self):
            self.pending = ""
            self.rows = 0
            self.last_seq = 0
            self.text_parts = []
            self.result = None

        def isatty(self):
            return False

        def write(self, chunk):
            self.pending += chunk
            while "\n" in self.pending:
                line, self.pending = self.pending.split("\n", 1)
                if not line:
                    continue
                row = json.loads(line)
                self.rows += 1
                assert row["seq"] == self.rows
                self.last_seq = row["seq"]
                if row["type"] == "text_delta":
                    self.text_parts.append(row["text"])
                elif row["type"] == "result":
                    self.result = row
            return len(chunk)

        def flush(self):
            return None

    sink = StreamingSink()
    monkeypatch.setattr(sys, "stdout", sink)
    view = Presenter("jsonl")
    expected_parts = [f"{number:05d}," for number in range(10_000)]
    expected = "".join(expected_parts)
    durations = []
    tracemalloc.start()
    try:
        view.started("stress-session", "stress-generation")
        for part in expected_parts:
            started = time.perf_counter()
            view.delta(StreamDelta(text=part))
            durations.append(time.perf_counter() - started)
        assert view.finish(LoopResult("stress-session", expected)) == 0
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sink.rows == 10_002 and sink.last_seq == 10_002
    assert "".join(sink.text_parts) == expected
    assert sink.result is not None
    assert sink.result["final_answer"] == expected and sink.result["status"] == "completed"
    # The fixed 10k-event workload must remain comfortably below 8 MiB even
    # with exact final-text retention and per-event JSON framing.
    assert peak_bytes < 8 * 1024 * 1024
    assert sorted(durations)[int(len(durations) * 0.95)] < 0.2


def test_external_editor_failure_preserves_draft(monkeypatch, tmp_path):
    from llm_loop.terminal.editor import Composer

    composer = Composer(UISettings(), tmp_path)
    composer.draft = "  original\n中文 👩‍💻  "
    monkeypatch.setenv("EDITOR", "failing-editor")
    monkeypatch.setattr(
        "llm_loop.terminal.editor.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(9, ["failing-editor"])),
    )
    with pytest.raises(ValueError, match="draft unchanged"):
        composer.external_edit()
    assert composer.draft == "  original\n中文 👩‍💻  "


def test_corrupt_ui_settings_fall_back_without_starting_a_run(monkeypatch, tmp_path, capsys):
    from llm_loop.core.session import SessionStore
    from llm_loop.terminal.shell import interactive_session

    store = SessionStore(str(tmp_path / "data"))
    sid = store.create()
    callbacks = []
    engine = SimpleNamespace(
        session=store,
        registry=SimpleNamespace(set_approval_callback=callbacks.append),
        correction_ctx=None,
        settings=None,
    )
    monkeypatch.setattr(
        "llm_loop.terminal.shell.load_ui",
        lambda: (_ for _ in ()).throw(ValueError("corrupt display settings")),
    )
    monkeypatch.setattr("llm_loop.terminal.shell.Composer.read", lambda self, *_a: "/exit")
    assert interactive_session(engine, sid) == 0
    assert len(callbacks) == 1
    assert "using defaults" in capsys.readouterr().err


def test_saved_terminal_installs_guard_before_snapshot_and_preserves_body_handler(monkeypatch):
    import signal
    import termios

    from llm_loop.terminal import state

    class TTY:
        @staticmethod
        def isatty():
            return True

        @staticmethod
        def fileno():
            return 42

    events = []
    current: dict[str, object] = {"handler": signal.SIG_DFL}

    def get_handler(_signum):
        return current["handler"]

    def set_handler(_signum, handler):
        events.append("handler")
        current["handler"] = handler

    def get_modes(fd):
        assert fd == 42
        events.append("snapshot")
        return [1, 2, 3]

    def set_modes(fd, when, modes):
        assert (fd, when, modes) == (42, termios.TCSANOW, [1, 2, 3])
        events.append("restore")

    monkeypatch.setattr(state.sys, "stdin", TTY())
    monkeypatch.setattr(state.signal, "getsignal", get_handler)
    monkeypatch.setattr(state.signal, "signal", set_handler)
    monkeypatch.setattr(termios, "tcgetattr", get_modes)
    monkeypatch.setattr(termios, "tcsetattr", set_modes)
    def body_handler(_signum: int, _frame: object) -> None:
        return None

    with state.saved_terminal():
        outer_handler = current["handler"]
        assert outer_handler is not signal.SIG_DFL
        with state.saved_terminal():
            assert current["handler"] is outer_handler
            current["handler"] = body_handler

    assert events.index("handler") < events.index("snapshot")
    assert events.count("snapshot") == 2 and events.count("restore") == 2
    assert current["handler"] is body_handler


def test_resume_switches_exact_session_without_creating_or_running(monkeypatch, tmp_path):
    from llm_loop.core.session import SessionStore
    from llm_loop.terminal.shell import interactive_session

    store = SessionStore(str(tmp_path / "data"))
    first, second = store.create(), store.create()
    before = {meta.session_id for meta in store.list_sessions()}
    reads = []
    commands = iter((f"/resume {second}", "/exit"))
    callbacks = []
    engine = SimpleNamespace(
        session=store,
        registry=SimpleNamespace(set_approval_callback=callbacks.append),
        correction_ctx=None,
        settings=None,
        run=lambda *_a, **_kw: pytest.fail("local resume must not start a model run"),
    )

    def read(_composer, sid, *_args):
        reads.append(sid)
        return next(commands)

    monkeypatch.setattr("llm_loop.terminal.shell.Composer.read", read)
    assert interactive_session(engine, first) == 0
    assert reads == [first, second]
    assert {meta.session_id for meta in store.list_sessions()} == before
    assert len(callbacks) == 1


def test_no_color_markdown_projection_is_linear_and_inert(monkeypatch):
    from llm_loop.terminal.markdown import render_markdown

    class TTY(io.StringIO):
        def isatty(self):
            return True

    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr("llm_loop.terminal.markdown.legacy_env_snapshot", lambda: {})
    source = "# Title\n\n```python\nprint('safe')\n```"
    render_markdown(source, width=80)
    colored = output.getvalue()
    assert re.search(r"\x1b\[(?:[0-9;]*;)?(?:3[0-7]|9[0-7]|38)(?:;|m)", colored), (
        "positive control must demonstrate that this terminal emits color without NO_COLOR"
    )
    output.seek(0)
    output.truncate(0)
    monkeypatch.setattr("llm_loop.terminal.markdown.legacy_env_snapshot", lambda: {"NO_COLOR": "1"})
    render_markdown(source, width=80)
    rendered = output.getvalue()
    assert "Title" in rendered and "safe" in rendered
    # NO_COLOR disables color, not semantic emphasis such as bold/underline.
    for sequence in re.findall(r"\x1b\[([0-9;]*)m", rendered):
        params = [int(item or "0") for item in sequence.split(";")]
        assert not any(
            30 <= item <= 37 or 90 <= item <= 97 or 40 <= item <= 47
            or 100 <= item <= 107 or item in {38, 48}
            for item in params
        ), sequence


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
