"""Running-turn pre-input must stay separate from the owned run and its generation."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from llm_loop.core.loop import LoopResult
from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.llm.client import StreamDelta
from llm_loop.terminal.editor import Composer
from llm_loop.terminal.execution import run_turn
from llm_loop.terminal.presentation import Presenter
from llm_loop.terminal.settings import UISettings


def test_composer_preinput_is_nonblocking_and_keeps_draft_local(monkeypatch, tmp_path):
    monkeypatch.setattr(Composer, "supports_preinput", property(lambda _self: True), raising=False)
    composer = Composer(UISettings(), tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def read(sid: str, model: str = "") -> str:
        assert (sid, model) == ("session-a", "glm/glm-5.3")
        entered.set()
        assert release.wait(3), "test must release the local draft reader"
        return "next round\n中文"

    monkeypatch.setattr(composer, "read", read)
    assert composer.start_preinput("session-a", "glm/glm-5.3")
    try:
        assert entered.wait(1), "pre-input must start without waiting for the current run"
        assert composer.preinput_active
        current_run_text = "current request must not be replaced"
        assert current_run_text == "current request must not be replaced"
    finally:
        release.set()
    assert composer.finish_preinput() == "next round\n中文"
    assert not composer.preinput_active


def test_run_turn_starts_preinput_while_only_current_message_is_running():
    calls: list[tuple[str, str]] = []
    run_started = threading.Event()
    preinput_started = threading.Event()
    release = threading.Event()
    failures: list[str] = []

    class Engine:
        def __init__(self):
            self.runner = BackgroundRunner(self)

        def run_stream(self, sid, text, model=None, **kwargs):
            calls.append((sid, text))
            run_started.set()
            yield StreamDelta(text="current run output")
            if not release.wait(3):
                raise RuntimeError("test timed out waiting to release current run")
            return LoopResult(sid, "current run settled", model_used=model or "fixture/model")

    class DraftInput:
        def start_preinput(self, sid, model="", *, cancel_callback=None):
            assert (sid, model) == ("session-a", "glm/glm-5.3")
            assert callable(cancel_callback)
            preinput_started.set()
            return True

        def mark_preinput_run_settled(self):
            return None

        def abort_preinput(self):
            return True

    engine = Engine()
    draft = DraftInput()

    def release_after_preinput_starts():
        if not run_started.wait(2):
            failures.append("current run never started")
        elif not preinput_started.wait(2):
            failures.append("next-turn composer did not start during current run")
        else:
            if calls != [("session-a", "current request")]:
                failures.append(f"current run input changed or overlapped: {calls!r}")
        release.set()

    controller = threading.Thread(target=release_after_preinput_starts, daemon=True)
    controller.start()
    try:
        result = run_turn(
            engine, "session-a", "current request", Presenter(plain=True),
            interactive=True, preinput=draft, model="glm/glm-5.3",
        )
    finally:
        release.set()
        controller.join(timeout=3)
    assert result == 0
    assert calls == [("session-a", "current request")]
    assert preinput_started.is_set()
    assert not failures, failures
    assert not engine.runner.is_running("session-a")


def test_interactive_session_queues_preinput_only_after_current_turn_settles(
    monkeypatch, tmp_path,
):
    from llm_loop.core.session import SessionStore
    from llm_loop.terminal.shell import interactive_session

    store = SessionStore(str(tmp_path / "sessions"))
    sid = store.create()
    callbacks = []
    engine = SimpleNamespace(
        session=store,
        registry=SimpleNamespace(set_approval_callback=callbacks.append),
        correction_ctx=None,
        settings=None,
        _cli_workspace=tmp_path,
        _cli_plain=True,
    )
    timeline: list[tuple[str, str]] = []
    prompt_values = iter(("first request", "/exit"))
    queued_values = iter(("next request", None))

    monkeypatch.setattr("llm_loop.terminal.shell.load_ui", lambda: UISettings(plain=True))
    monkeypatch.setattr(Composer, "supports_preinput", property(lambda _self: True), raising=False)
    monkeypatch.setattr(Composer, "read", lambda *_args: next(prompt_values))

    def start_preinput(self, _sid, _model="", *, cancel_callback=None):
        self._test_preinput_result = next(queued_values)
        timeline.append(("preinput", self._test_preinput_result or ""))
        return self._test_preinput_result is not None

    def finish_preinput(self):
        value = getattr(self, "_test_preinput_result", None)
        self._test_preinput_result = None
        return value

    def mark_preinput_run_settled(self):
        timeline.append(("settled", ""))

    monkeypatch.setattr(Composer, "start_preinput", start_preinput, raising=False)
    monkeypatch.setattr(Composer, "finish_preinput", finish_preinput, raising=False)
    monkeypatch.setattr(Composer, "mark_preinput_run_settled", mark_preinput_run_settled, raising=False)

    def run(_engine, _sid, text, _view, _approval=None, *, interactive=False, preinput=None, model=""):
        assert interactive
        timeline.append(("run-start", text))
        if preinput is not None:
            preinput.start_preinput(_sid, model)
        timeline.append(("run-settled", text))
        return 0

    monkeypatch.setattr("llm_loop.terminal.shell.run_turn", run)
    assert interactive_session(engine, sid) == 0
    starts = [value for kind, value in timeline if kind == "run-start"]
    assert starts == ["first request", "next request"]
    assert timeline.index(("run-settled", "first request")) < timeline.index(("run-start", "next request"))
    assert len(callbacks) == 1


def test_run_turn_aborts_preinput_if_event_pump_raises(monkeypatch):
    from llm_loop.terminal import execution

    class Runner:
        enabled = True

        def __init__(self):
            self.unsubscribed = False

        def start(self, _sid, _text, **_kwargs):
            return SimpleNamespace(run_generation=1), object()

        def unsubscribe(self, _sid, _events):
            self.unsubscribed = True

    class DraftInput:
        aborted = False

        def start_preinput(self, _sid, _model="", *, cancel_callback=None):
            assert callable(cancel_callback)
            return True

        def abort_preinput(self):
            self.aborted = True
            return True

    runner = Runner()
    draft = DraftInput()
    engine = SimpleNamespace(runner=runner)

    def fail_pump(*_args, **_kwargs):
        raise RuntimeError("synthetic pump failure")

    monkeypatch.setattr(execution, "_pump", fail_pump)
    with pytest.raises(RuntimeError, match="synthetic pump failure"):
        run_turn(
            engine, "session-a", "current request", Presenter(plain=True),
            interactive=True, preinput=draft, model="glm/glm-5.3",
        )
    assert draft.aborted
    assert runner.unsubscribed
