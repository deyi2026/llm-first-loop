"""Real PTY composer checks: Unicode/paste/multiline and terminal restoration."""
from __future__ import annotations

import json
import os
import select
import signal
import struct
import subprocess
import sys
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
