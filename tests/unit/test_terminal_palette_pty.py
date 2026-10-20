"""Real PTY lifecycle for R15: Esc closes the modal, restores terminal state."""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY requires POSIX")


@pytest.mark.parametrize(("keys", "expected"), [
    (b"\x1b", b"SELECTION:None"),
    (b"\t\r", b"SELECTION:'/help'"),
])
def test_r15_palette_selection_or_escape_restores_terminal(
    tmp_path: Path, keys: bytes, expected: bytes,
) -> None:
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    saved = termios.tcgetattr(slave)
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               PYTHONPATH=str(root / "src"))
    script = (
        "from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(),Path.cwd()); c.draft='original 中文'; "
        "selected=c.select_command(); "
        "print('SELECTION:'+repr(selected),flush=True); "
        "print('DRAFT:'+repr(c.draft),flush=True); "
        "echo=input('COOKED> '); print('ECHO:'+echo,flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script], stdin=slave, stdout=slave,
        stderr=slave, env=env, cwd=tmp_path,
    )
    output = bytearray()

    def receive(needle: bytes, timeout: float = 6.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.08)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")

    try:
        receive(b"LFL commands")
        os.write(master, keys)
        receive(expected, timeout=8)
        receive(b"DRAFT:'original", timeout=2)
        # macOS Darwin PENDIN is transient until a real cooked read performs
        # terminal handoff; do not mask away changed termios flags.
        receive(b"COOKED> ", timeout=2)
        os.write(master, b"returned\r")
        receive(b"ECHO:returned", timeout=2)
        process.wait(timeout=3)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == saved
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)
