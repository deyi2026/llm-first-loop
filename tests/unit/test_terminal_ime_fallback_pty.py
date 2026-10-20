"""T03/T04: real terminal key/paste fallback (not physical OS IME certification)."""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY required")


@pytest.mark.parametrize(
    ("multiline", "keys", "expected"),
    [
        (False, "FIRST\x1b\r中文😀\r".encode(), "FIRST\n中文😀"),
        (True, "拼音输入\rEnglish e\u0301\x18s".encode(), "拼音输入\nEnglish e\u0301"),
    ],
)
def test_ime_safe_explicit_newline_does_not_submit_composition(
    tmp_path: Path, multiline: bool, keys: bytes, expected: str,
) -> None:
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               PYTHONPATH=str(repo / "src"))
    script = (
        "from pathlib import Path;"
        "from llm_loop.terminal.editor import Composer;"
        "from llm_loop.terminal.settings import UISettings;"
        f"c=Composer(UISettings(multiline={multiline}),Path.cwd());"
        "print('READY_PROMPT',flush=True);"
        "print('RESULT:'+repr(c.read('s','glm')),flush=True);"
        "print('COOKED>',flush=True);"
        "print('ECHO:'+input(),flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        stdin=slave, stdout=slave, stderr=slave,
    )
    output = bytearray()

    def receive(needle: bytes, timeout: float = 7.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], .06)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")[-900:]

    try:
        receive("你".encode())
        os.write(master, keys)
        receive(("RESULT:" + repr(expected)).encode())
        receive(b"COOKED>")
        os.write(master, b"ack\r")
        receive(b"ECHO:ack")
        process.wait(timeout=3)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)
