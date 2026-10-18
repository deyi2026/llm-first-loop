"""Real PTY composer checks: Unicode/paste/multiline and terminal restoration."""
from __future__ import annotations

import json
import os
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY is a POSIX terminal contract")


@pytest.mark.parametrize(("width", "height", "multiline"), [
    (60, 12, False), (100, 24, False), (140, 30, True),
])
def test_composer_paste_requires_explicit_submit_and_restores_terminal(tmp_path, width, height, multiline):
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
        payload = "  中文 e\u0301 👩‍💻\nline two  "
        os.write(master, b"\x1b[200~" + payload.encode() + b"\x1b[201~")
        time.sleep(0.15)
        assert process.poll() is None, "pasting must not submit the message"
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
