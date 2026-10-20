"""Real PTY composer checks: Unicode/paste/multiline and terminal restoration."""
from __future__ import annotations

import json
import os
import select
import signal
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY is a POSIX terminal contract")


def _assert_absent_for(master, output, needle, timeout=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([master], [], [], 0.02)[0]:
            try:
                output.extend(os.read(master, 65536))
            except OSError:
                break
        assert needle not in output, output.decode(errors="replace")


@pytest.mark.parametrize(("width", "height", "multiline", "resize", "line_count"), [
    (60, 12, False, None, 2),
    (100, 24, False, None, 2),
    (140, 30, True, None, 2),
    (80, 24, False, (120, 40), 2),
    (120, 40, False, (48, 12), 2),
    (48, 12, True, (80, 24), 2),
    (100, 24, True, None, 100),
])
def test_composer_paste_requires_explicit_submit_and_restores_terminal(
    tmp_path, width, height, multiline, resize, line_count,
):
    pytest.importorskip("prompt_toolkit")
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "import json; from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        f"c=Composer(UISettings(multiline={multiline!r}),Path.cwd()); "
        "s=c.read('fixture','test/model'); print('RESULT:'+json.dumps(s,ensure_ascii=True),flush=True); "
        "echo=input('COOKED> '); print('ECHO:'+echo,flush=True)"
    )
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        if resize is not None:
            # Discard the initial frame, then wait for the post-SIGWINCH redraw
            # instead of sleeping and possibly pasting before the UI reacts.
            output.clear()
            fcntl.ioctl(slave, termios.TIOCSWINSZ,
                        struct.pack("HHHH", resize[1], resize[0], 0, 0))
            os.kill(process.pid, signal.SIGWINCH)
            receive_until(b"\x1b[J")
            assert process.poll() is None
        if line_count == 2:
            payload = "  中文 e\u0301 👩‍💻\nline two  "
        else:
            lines = ["  中文 e\u0301 👩‍💻", "", "```python"]
            lines.extend(f"print({number})  # 宽字符 🧪" for number in range(4, 100))
            lines.append("```")
            assert len(lines) == line_count
            payload = "\n".join(lines)
        os.write(master, b"\x1b[200~" + payload.encode() + b"\x1b[201~")
        _assert_absent_for(master, output, b"RESULT:")  # bracketed paste must not submit
        os.write(master, b"\x18s" if multiline else b"\r")
        receive_until(b"RESULT:")
        receive_until(b"COOKED>")
        # Exercise a real ordinary read after handing the terminal back. On Darwin
        # ICANON transitions may leave PENDIN until this read reprocesses input.
        # No flag masking: all original modes must match after native handoff.
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=6)
        # Read any final bytes before checking the complete result marker.
        while select.select([master], [], [], 0.05)[0]:
            output.extend(os.read(master, 65536))
        line = bytes(output).split(b"RESULT:", 1)[1].splitlines()[0]
        assert json.loads(line) == payload
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_tab_completes_slash_command_and_enter_submits_exact_completion(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "import json; from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(),Path.cwd()); "
        "s=c.read('fixture','test/model'); print('RESULT:'+json.dumps(s),flush=True); "
        "echo=input('COOKED> '); print('ECHO:'+echo,flush=True)"
    )
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        os.write(master, b"/hel\t")
        receive_until(b"/help")  # synchronize on the completed buffer, not elapsed time
        os.write(master, b"\r")
        receive_until(b"RESULT:")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=6)
        line = bytes(output).split(b"RESULT:", 1)[1].splitlines()[0]
        assert json.loads(line) == "/help"
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_dumb_terminal_uses_explicit_plain_multiline_fallback(tmp_path):
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="dumb", XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "import json; from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(multiline=True),Path.cwd()); "
        "s=c.read('fixture','test/model'); print('RESULT:'+json.dumps(s,ensure_ascii=False),flush=True)"
    )
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until(b"[multiline]")
        os.write(master, "中文\n..\n.\n".encode())
        receive_until(b"RESULT:")
        process.wait(timeout=6)
        line = bytes(output).split(b"RESULT:", 1)[1].splitlines()[0]
        assert json.loads(line) == "中文\n."
        assert b"\x1b" not in output
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_sigterm_during_composer_restores_terminal_modes(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = (
        "from pathlib import Path; from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "Composer(UISettings(),Path.cwd()).read('fixture','test/model')"
    )
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()
    try:
        deadline = time.monotonic() + 6
        while "你".encode() not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert "你".encode() in output, output.decode(errors="replace")
        os.kill(process.pid, signal.SIGTERM)
        process.wait(timeout=6)
        assert process.returncode == 143
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_running_turn_can_collect_next_draft_before_current_run_settles(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = textwrap.dedent(
        """
        import json
        import time
        from pathlib import Path
        from llm_loop.terminal.editor import Composer
        from llm_loop.terminal.settings import UISettings

        composer = Composer(UISettings(), Path.cwd())
        assert composer.start_preinput("fixture", "test/model")
        print("RUN_ACTIVE", flush=True)
        time.sleep(0.35)
        print("STREAM_EVENT:current-run-still-active", flush=True)
        deadline = time.monotonic() + 5
        while composer.preinput_active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not composer.preinput_active, "draft was not captured while current run was active"
        print("DRAFT_CAPTURED_WHILE_RUN_ACTIVE", flush=True)
        composer.mark_preinput_run_settled()
        draft = composer.finish_preinput()
        print("DRAFT:" + json.dumps(draft, ensure_ascii=False), flush=True)
        echo = input("COOKED> ")
        print("ECHO:" + echo, flush=True)
        """
    ).strip()
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        receive_until(b"STREAM_EVENT:current-run-still-active")
        _assert_absent_for(master, output, b"DRAFT:")
        assert process.poll() is None
        os.write(master, "next round 中文\r".encode())
        receive_until(b"DRAFT_CAPTURED_WHILE_RUN_ACTIVE")
        receive_until(b"DRAFT:")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=6)
        line = bytes(output).split(b"DRAFT:", 1)[1].splitlines()[0]
        assert json.loads(line) == "next round 中文"
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_ctrl_c_in_next_draft_requests_current_run_cancel_and_stashes_text(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = textwrap.dedent(
        """
        import json
        import time
        import threading
        from pathlib import Path
        from llm_loop.terminal.editor import Composer
        from llm_loop.terminal.settings import UISettings

        composer = Composer(UISettings(), Path.cwd())
        cancelled = threading.Event()
        assert composer.start_preinput("fixture", "test/model", cancel_callback=cancelled.set)
        time.sleep(0.35)
        print("CANCEL_WINDOW", flush=True)
        deadline = time.monotonic() + 5
        while composer.preinput_active and time.monotonic() < deadline:
            time.sleep(0.01)
        print("CANCELLED:" + str(cancelled.is_set()), flush=True)
        print("STASHED:" + composer.stashed, flush=True)
        composer.mark_preinput_run_settled()
        draft = composer.finish_preinput()
        print("DRAFT:" + json.dumps(draft), flush=True)
        echo = input("COOKED> ")
        print("ECHO:" + echo, flush=True)
        """
    ).strip()
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        receive_until(b"CANCEL_WINDOW")
        os.write(master, b"unfinished draft")
        os.write(master, b"\x03")
        receive_until(b"CANCELLED:True")
        receive_until(b"STASHED:unfinished draft")
        receive_until(b"DRAFT:")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=6)
        line = bytes(output).split(b"DRAFT:", 1)[1].splitlines()[0]
        assert json.loads(line) == ""
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_abort_preinput_stashes_text_and_restores_terminal(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = textwrap.dedent(
        """
        import time
        from pathlib import Path
        from llm_loop.terminal.editor import Composer
        from llm_loop.terminal.settings import UISettings

        composer = Composer(UISettings(), Path.cwd())
        assert composer.start_preinput("fixture", "test/model")
        print("ABORT_WINDOW", flush=True)
        time.sleep(0.35)
        print("ABORT_NOW", flush=True)
        stopped = composer.abort_preinput(timeout=3)
        print("ABORTED:" + str(stopped), flush=True)
        print("STASHED:" + composer.stashed, flush=True)
        echo = input("COOKED> ")
        print("ECHO:" + echo, flush=True)
        """
    ).strip()
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=6):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        os.write(master, b"unfinished draft")
        receive_until(b"ABORT_NOW")
        receive_until(b"ABORTED:True")
        receive_until(b"STASHED:unfinished draft")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=6)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_sigterm_during_run_aborts_next_draft_and_restores_terminal(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import signal
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = textwrap.dedent(
        """
        import time
        from pathlib import Path
        from llm_loop.core.loop import LoopResult
        from llm_loop.core.loop.runner import BackgroundRunner
        from llm_loop.llm.client import StreamDelta
        from llm_loop.terminal.editor import Composer
        from llm_loop.terminal.execution import run_turn
        from llm_loop.terminal.presentation import Presenter
        from llm_loop.terminal.settings import UISettings

        class Engine:
            def __init__(self):
                self.runner = BackgroundRunner(self)

            def run_stream(self, sid, text, model=None, **kwargs):
                yield StreamDelta(text="current run output")
                time.sleep(1.2)
                return LoopResult(sid, "settled after termination request", model_used=model or "fixture/model")

        engine = Engine()
        composer = Composer(UISettings(), Path.cwd())
        result = run_turn(
            engine, "fixture", "current request", Presenter(plain=True),
            interactive=True, preinput=composer, model="fixture/model",
        )
        print("RUN_EXIT:" + str(result), flush=True)
        print("STASHED:" + composer.stashed, flush=True)
        echo = input("COOKED> ")
        print("ECHO:" + echo, flush=True)
        """
    ).strip()
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=8):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        receive_until(b"current run output")
        os.write(master, b"unfinished draft")
        os.kill(process.pid, signal.SIGTERM)
        receive_until(b"RUN_EXIT:143")
        receive_until(b"STASHED:unfinished draft")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=8)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_sigterm_while_waiting_for_next_draft_after_run_settled_restores_terminal(tmp_path):
    pytest.importorskip("prompt_toolkit")
    import pty
    import signal
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    script = textwrap.dedent(
        """
        from pathlib import Path
        from llm_loop.terminal.editor import Composer
        from llm_loop.terminal.shell import _preinput_signal_guard
        from llm_loop.terminal.settings import UISettings

        composer = Composer(UISettings(), Path.cwd())
        assert composer.start_preinput("fixture", "test/model")
        with _preinput_signal_guard(composer) as (interrupted, terminated):
            composer.mark_preinput_run_settled()
            print("RUN_SETTLED_WAITING_DRAFT", flush=True)
            draft = composer.finish_preinput()
            exit_code = 143 if terminated.is_set() else 0
            print("EXIT:" + str(exit_code), flush=True)
        print("STASHED:" + composer.stashed, flush=True)
        echo = input("COOKED> ")
        print("ECHO:" + echo, flush=True)
        """
    ).strip()
    process = subprocess.Popen([sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
                               stderr=slave, env=env)
    output = bytearray()

    def receive_until(needle, timeout=8):
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive_until("你".encode())
        receive_until(b"RUN_SETTLED_WAITING_DRAFT")
        os.write(master, b"unfinished after run settled")
        os.kill(process.pid, signal.SIGTERM)
        receive_until(b"EXIT:143")
        receive_until(b"STASHED:unfinished after run settled")
        receive_until(b"COOKED>")
        os.write(master, b"returned\r")
        receive_until(b"ECHO:returned")
        process.wait(timeout=8)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)
