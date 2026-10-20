"""T17 real POSIX alternate-screen, keyboard focus, draft and termios restoration."""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY required")


def test_t17_optional_fullscreen_navigation_restores_existing_composer(
    tmp_path: Path,
) -> None:
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
        PYTHONPATH=str(root / "src"),
    )
    script = (
        "from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(),Path.cwd()); c.draft='原始草稿 123'; "
        "c.record_source=lambda _: {'messages':[{'role':'user','content':'prior view'},"
        "{'role':'tool','content':'diff --git a/f b/f\\n--- a/f\\n+++ b/f\\n'}]}; "
        "print('START_FULLSCREEN',flush=True); "
        "res=c.show_records('sid',['full']); "
        "print('VIEW_CLOSED:'+res,flush=True); "
        "print('DRAFT:'+repr(c.draft),flush=True); "
        "answer=input('COOKED> ');print('ECHO:'+answer,flush=True)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        stdin=slave, stdout=slave, stderr=slave,
    )
    seen = bytearray()

    def receive(needle: bytes, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in seen and time.monotonic() < deadline:
            if select.select([master], [], [], 0.06)[0]:
                try:
                    seen.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in seen, seen.decode(errors="replace")[-1500:]

    try:
        receive(b"LFL transcript")
        receive(b"prior view") if b"prior view" in seen else None
        os.write(master, b"d")
        receive(b"diff --git")
        os.write(master, b"l")
        receive(b"column 101")
        os.write(master, b"h")
        receive(b"column 1")
        os.write(master, b"q")
        receive(b"VIEW_CLOSED:")
        receive(b"COOKED> ")
        os.write(master, b"ok\r")
        receive(b"ECHO:ok")
        proc.wait(timeout=3)
        assert proc.returncode == 0
        assert "原始草稿 123" in seen.decode(errors="replace")
        assert termios.tcgetattr(slave) == original
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        os.close(master)
        os.close(slave)
