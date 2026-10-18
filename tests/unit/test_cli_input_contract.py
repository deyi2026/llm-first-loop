"""CLI phase A: real entrypoint, isolated storage, no Provider or managed services."""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

import llm_loop.cli as cli
from llm_loop.core.loop import LoopResult
from llm_loop.core.session import SessionStore


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    calls = []
    approvals = []
    closed = []
    engines = []
    bootstrap = []
    sessions = SessionStore(str(tmp_path / "sessions"))
    result = LoopResult(session_id="fixture", final_answer="answer")
    engine = SimpleNamespace(
        session=sessions,
        correction_ctx=None,
        registry=SimpleNamespace(set_approval_callback=approvals.append),
        close=lambda: closed.append(True),
    )

    def run(sid, text, **kwargs):
        calls.append((sid, text))
        return result

    engine.run = run

    def build(*args, **kwargs):
        engines.append(engine)
        return engine

    monkeypatch.setattr("llm_loop.config.load_env_file", lambda *a, **k: bootstrap.append("env"))
    monkeypatch.setattr("llm_loop.introspection.proc_version.record_process_start", lambda *a: bootstrap.append("process"))
    monkeypatch.setattr(cli, "load_settings", lambda: object())
    monkeypatch.setattr("llm_loop.factory.build_engine", build)
    monkeypatch.setattr(cli.sys, "stdin", TTY())
    return SimpleNamespace(
        engine=engine, result=result, calls=calls, approvals=approvals,
        closed=closed, engines=engines, bootstrap=bootstrap, sessions=sessions,
    )


def test_missing_session_is_nonzero_and_does_not_create_replacement(runtime):
    before = runtime.sessions.list_sessions()
    assert cli.main(["--session", "missing", "hello"]) == 1
    assert runtime.calls == []
    assert runtime.sessions.list_sessions() == before
    assert runtime.closed == [True]


@pytest.mark.parametrize("flag", [
    "run_incomplete", "provider_output_truncated", "projection_cannot_fit",
])
def test_incomplete_engine_facts_cannot_be_success(runtime, flag):
    setattr(runtime.result, flag, True)
    assert cli.main(["hello"]) == 1
    assert len(runtime.calls) == 1
    assert runtime.closed == [True]


def test_cancelled_engine_result_cannot_be_success(runtime):
    runtime.result.cancel_reason = "user_stop"
    assert cli.main(["hello"]) == 1
    assert runtime.closed == [True]


def test_history_compaction_alone_is_not_a_failed_run(runtime):
    runtime.result.history_compacted = True
    assert cli.main(["hello"]) == 0


@pytest.mark.parametrize("argv", [[], ["--interactive"]])
def test_effective_interactive_modes_receive_the_same_approval(runtime, monkeypatch, argv):
    monkeypatch.setattr("builtins.input", lambda *a: "exit")
    assert cli.main(argv) == 0
    assert len(runtime.approvals) == 1
    assert runtime.closed == [True]


def test_non_tty_without_explicit_input_never_bootstraps(runtime, monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("first\nsecond\n"))
    assert cli.main([]) == 2
    assert runtime.bootstrap == []
    assert runtime.engines == []


def test_explicit_stdin_is_one_exact_message(runtime, monkeypatch):
    content = "  first line\n\nsecond line\n"
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(content))
    assert cli.main(["--stdin"]) == 0
    assert [text for _, text in runtime.calls] == [content]
    assert runtime.approvals == []


def test_stdin_preserves_crlf_and_bare_cr_exactly(runtime, monkeypatch):
    raw = b"first\r\nsecond\rthird\n"
    stream = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", newline=None)
    monkeypatch.setattr(cli.sys, "stdin", stream)
    assert cli.main(["--stdin"]) == 0
    assert [text for _, text in runtime.calls] == [raw.decode("utf-8")]


@pytest.mark.parametrize("argv", [
    ["hello", "--stdin"],
    ["--interactive", "--stdin"],
    ["hello", "--interactive"],
    ["hello", "--message-file", "unused"],
])
def test_conflicting_inputs_do_not_bootstrap(runtime, argv):
    assert cli.main(argv) == 2
    assert runtime.bootstrap == []
    assert runtime.engines == []


def test_non_tty_interactive_does_not_wait_for_input(runtime, monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    assert cli.main(["--interactive"]) == 2
    assert runtime.engines == []


@pytest.mark.parametrize("content", ["", " \n\t"])
def test_empty_stdin_does_not_create_a_run(runtime, monkeypatch, content):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(content))
    assert cli.main(["--stdin"]) == 2
    assert runtime.engines == []
    assert runtime.closed == []


def test_message_file_preserves_utf8_bytes_as_text(runtime, tmp_path):
    message = tmp_path / "message.txt"
    content = "  中文\n\nnext line\n"
    message.write_text(content, encoding="utf-8")
    assert cli.main(["--message-file", str(message)]) == 0
    assert [text for _, text in runtime.calls] == [content]


def test_invalid_message_file_does_not_bootstrap(runtime, tmp_path):
    message = tmp_path / "invalid.txt"
    message.write_bytes(bytes([255]))
    assert cli.main(["--message-file", str(message)]) == 2
    assert runtime.engines == []


@pytest.mark.parametrize("argv", [
    ["hello", "--model", "requested/model"],
    ["--interactive", "--model", "requested/model"],
])
def test_unavailable_startup_model_never_runs_the_default(runtime, argv):
    assert cli.main(argv) == 1
    assert runtime.calls == []
    assert runtime.closed == [True]


def test_failed_model_switch_stops_before_run(runtime, monkeypatch):
    runtime.engine.correction_ctx = object()
    monkeypatch.setattr(
        "llm_loop.introspection.model_command.handle_model_command",
        lambda *a, **k: SimpleNamespace(success=False, reply="fixture rejection"),
    )
    assert cli.main(["hello", "--model", "bad/model"]) == 1
    assert runtime.calls == []
    assert runtime.closed == [True]


@pytest.mark.parametrize("argv", [
    ["hello", "--model", "bad/model"],
    ["--interactive", "--model", "bad/model"],
])
def test_failed_startup_model_does_not_leave_new_empty_session(runtime, monkeypatch, argv):
    runtime.engine.correction_ctx = object()
    monkeypatch.setattr(
        "llm_loop.introspection.model_command.handle_model_command",
        lambda *a, **k: SimpleNamespace(success=False, reply="fixture rejection"),
    )
    before = runtime.sessions.list_sessions()
    assert cli.main(argv) == 1
    assert runtime.calls == []
    assert runtime.sessions.list_sessions() == before
    assert runtime.closed == [True]


def test_non_tty_approval_cannot_consume_pipeline_input(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("yes\n"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("must not read non-TTY"))
    assert cli._cli_approval_prompt("fixture", "fixture") is False



def test_unexpected_none_model_reply_stops_before_run(runtime, monkeypatch):
    runtime.engine.correction_ctx = object()
    monkeypatch.setattr(
        "llm_loop.introspection.model_command.handle_model_command",
        lambda *a, **k: None,
    )
    assert cli.main(["hello", "--model", "fixture/model"]) == 1
    assert runtime.calls == []
    assert runtime.closed == [True]
