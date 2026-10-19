"""R13: true-TTY Markdown streaming never changes the run's exact source."""
from __future__ import annotations

import io
import re
import sys
import time
import tracemalloc
from types import SimpleNamespace

from llm_loop.terminal.presentation import Presenter


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def _visible(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def test_tty_closed_markdown_blocks_render_once_without_rewriting_history(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr("llm_loop.terminal.markdown.legacy_env_snapshot", lambda: {"NO_COLOR": "1"})
    view = Presenter(plain=False)
    assert view._markdown is not None
    view.started("sid", "generation-1")
    pieces = ["# 你", "好\n\n", "First **bo", "ld** paragraph.\n\n", "```python\n", "    x = '你'\n", "```\n"]
    for piece in pieces:
        view.delta(SimpleNamespace(text=piece, tool_round=None, tool_result=None))
    exact = "".join(pieces)
    assert view.finish(SimpleNamespace(final_answer=exact, session_id="sid", rounds=1,
                                       model_used="fake", tokens_in=1, tokens_out=1,
                                       fallback_receipt="")) == 0
    seen = _visible(output.getvalue())
    assert seen.count("你好") == 1
    assert seen.count("First bold paragraph.") == 1
    assert "    x = '你'" in seen
    assert output.getvalue().count("```python") == 1
    assert view.text == exact


def test_tty_idle_partial_is_shown_without_duplicate_or_hidden_tail(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="unfinished ", tool_round=None, tool_result=None))
    assert view._markdown is not None
    view._markdown._pending_since = 0
    view._markdown._clock = lambda: 1
    view.tick()
    assert output.getvalue() == "unfinished "
    view.delta(SimpleNamespace(text="paragraph", tool_round=None, tool_result=None))
    view.finish(SimpleNamespace(final_answer="unfinished paragraph", session_id="sid", rounds=0,
                                model_used="fake", tokens_in=0, tokens_out=0,
                                fallback_receipt=""))
    assert output.getvalue() == "unfinished paragraph\n"


def test_markdown_stream_sanitizes_control_bytes_in_open_fence_and_error(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    source = "```sh\nprint('ok')\n\x1b]0;bad-title\x07\n"
    view.delta(SimpleNamespace(text=source, tool_round=None, tool_result=None))
    assert view.error("partial run", "interrupted") == 1
    seen = output.getvalue()
    assert "\x1b]0;bad-title" not in seen
    assert "\\x1b]0;bad-title\\x07" in seen
    assert "print('ok')" in seen
    assert view.text == source


def test_inline_renderer_limits_pending_buffer_and_keeps_stream_order(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    source = "".join(f"{i % 10}" for i in range(10_000))
    tracemalloc.start()
    durations = []
    try:
        for character in source:
            started = time.perf_counter()
            view.delta(SimpleNamespace(text=character, tool_round=None, tool_result=None))
            durations.append(time.perf_counter() - started)
        view.finish(SimpleNamespace(final_answer=source, session_id="sid", rounds=1,
                                    model_used="fake", tokens_in=1, tokens_out=1,
                                    fallback_receipt=""))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert view.text == source
    assert output.getvalue() == source + "\n"
    assert sorted(durations)[int(len(durations) * 0.95)] < 0.2  # design p95 for fixed fake stream
    assert peak < 10_000_000


def test_piped_text_never_uses_tty_markdown_projection(capsys):
    view = Presenter(mode="text", plain=True)
    assert view._markdown is None
    view.delta(SimpleNamespace(text="# raw **syntax**", tool_round=None, tool_result=None))
    assert capsys.readouterr().out == "# raw **syntax**"


def test_term_dumb_disables_rich_tty_stream_even_with_fake_tty(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr("llm_loop.terminal.presentation.legacy_env_snapshot", lambda: {"TERM": "dumb"})
    view = Presenter(plain=False)
    assert view.plain and view._markdown is None
    view.delta(SimpleNamespace(text="**plain**", tool_round=None, tool_result=None))
    assert output.getvalue() == "**plain**"


def test_real_pty_event_pump_shows_partial_before_settlement_and_restores_terminal(tmp_path):
    import os
    import pty
    import select
    import subprocess
    import termios
    import textwrap
    from pathlib import Path

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent("""
        import time
        from llm_loop.core.loop import LoopResult
        from llm_loop.core.loop.runner import BackgroundRunner
        from llm_loop.llm.client import StreamDelta
        from llm_loop.terminal.execution import run_turn
        from llm_loop.terminal.presentation import Presenter

        class Engine:
            def __init__(self):
                self.runner = BackgroundRunner(self)
            def run_stream(self, sid, text, model=None, **kwargs):
                yield StreamDelta(text="partial ")
                time.sleep(0.35)
                yield StreamDelta(text="message\\n\\n# Header\\n\\n```python\\n    x = '好'\\n```\\n")
                return LoopResult(sid, "partial message\\n\\n# Header\\n\\n```python\\n    x = '好'\\n```\\n", model_used="fixture")

        print("START", flush=True)
        rc = run_turn(Engine(), "fixture", "one request", Presenter(plain=False))
        print("RUN_EXIT=" + str(rc), flush=True)
    """).strip()
    env = dict(os.environ, TERM="xterm-256color", NO_COLOR="1", PROMPT_TOOLKIT_NO_CPR="1",
               PYTHONPATH=str(root / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    proc = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                            stderr=slave, env=env)
    output = bytearray()

    def collect_until(needle: bytes, timeout: float = 7) -> None:
        until = time.monotonic() + timeout
        while needle not in output and time.monotonic() < until:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        collect_until(b"START")
        collect_until(b"partial ", timeout=3)
        assert b"RUN_EXIT=0" not in output  # exact user-visible progress before settlement
        collect_until(b"RUN_EXIT=0")
        seen = output.decode(errors="replace")
        assert seen.count("partial message") == 1
        assert seen.count("Header") == 1
        assert "    x = '好'" in seen
        assert b"\x1b]" not in output
        assert proc.wait(timeout=4) == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=4)
        os.close(master)
        os.close(slave)


def test_completed_heading_then_partial_same_delta_still_flushes_on_idle(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="# Title\nnext", tool_round=None, tool_result=None))
    assert view._markdown is not None
    assert view._markdown._pending_since is not None
    started = view._markdown._pending_since
    view._markdown._clock = lambda: started + 0.2
    view.tick()
    assert output.getvalue().count("next") == 1
    view.delta(SimpleNamespace(text=" line\n", tool_round=None, tool_result=None))
    view.finish(SimpleNamespace(final_answer="# Title\nnext line\n", session_id="sid",
                                rounds=0, model_used="fake", tokens_in=0, tokens_out=0,
                                fallback_receipt=""))
    assert output.getvalue().count("next line") == 1


def test_pending_text_is_flushed_before_tool_receipt(monkeypatch, capsys):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="before tool", tool_round=SimpleNamespace(
        tool_name="safe_read", status="running", args_summary="SECRET"), tool_result=None))
    assert "before tool" in output.getvalue()
    view.delta(SimpleNamespace(text=" after", tool_round=None, tool_result=None))
    view.finish(SimpleNamespace(final_answer="before tool after", session_id="sid",
                                rounds=0, model_used="fake", tokens_in=0, tokens_out=0,
                                fallback_receipt=""))
    assert "before tool after" in output.getvalue()
    assert "SECRET" not in output.getvalue() + capsys.readouterr().err


def test_after_fence_close_following_block_gets_new_idle_timer(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="```\nx\n```\ntail", tool_round=None, tool_result=None))
    assert view._markdown is not None and view._markdown._pending_since is not None
    started = view._markdown._pending_since
    assert started is not None
    view._markdown._clock = lambda: started + 0.2
    view.tick()
    assert output.getvalue().endswith("tail")



def test_explicit_synchronous_runner_keeps_legacy_immediate_text_stream(monkeypatch):
    from llm_loop.core.loop import LoopResult
    from llm_loop.terminal.execution import run_turn

    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)

    class Engine:
        runner = SimpleNamespace(enabled=False)

        @staticmethod
        def run_stream(sid, text, **_kwargs):
            yield SimpleNamespace(text="immediate", tool_round=None, tool_result=None)
            assert output.getvalue() == "immediate"
            return LoopResult(sid, "immediate", model_used="fake")

    view = Presenter(plain=False)
    assert view._markdown is not None
    assert run_turn(Engine(), "sid", "input", view) == 0
    assert view._markdown is None
    assert output.getvalue() == "immediate\n"



def test_idle_raw_line_followed_immediately_by_fence_stays_code_after_blank(monkeypatch):
    output = TTY()
    monkeypatch.setattr(sys, "stdout", output)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="preface\n", tool_round=None, tool_result=None))
    assert view._markdown is not None
    view._markdown._pending_since = 0.0
    view._markdown._clock = lambda: 1.0
    view.tick()
    view.delta(SimpleNamespace(text="```python\n", tool_round=None, tool_result=None))
    assert view._markdown._fence == "```"
    view.delta(SimpleNamespace(text="\n**literal code**\n```\n", tool_round=None, tool_result=None))
    assert view._markdown._fence is None
    assert "**literal code**" in output.getvalue()


def test_notice_flushes_pending_text_before_diagnostic(monkeypatch):
    merged = TTY()
    monkeypatch.setattr(sys, "stdout", merged)
    monkeypatch.setattr(sys, "stderr", merged)
    view = Presenter(plain=False)
    view.started("sid", "g")
    view.delta(SimpleNamespace(text="partial before", tool_round=None, tool_result=None))
    view.notice("[waiting for model]")
    assert "partial before[waiting for model]" in merged.getvalue()
