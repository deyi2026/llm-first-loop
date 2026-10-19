"""T08: Ctrl+X o opens a real viewer during next-turn drafting, not a new run."""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY required")


def test_t08_running_prompt_record_focus_never_queues_browser_command(
    tmp_path: Path,
) -> None:
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    saved = termios.tcgetattr(slave)
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               PYTHONPATH=str(root / "src"))
    code = """
from pathlib import Path
from llm_loop.terminal.editor import Composer
from llm_loop.terminal.settings import UISettings

c=Composer(UISettings(),Path.cwd())
c.record_source=lambda sid:{'messages':[{'role':'user','content':'browse-only-history'}]}
c.draft='保留草稿 123'
print('START_FAKE_RUN',flush=True)
assert c.start_preinput('sid','glm/glm-5.3')
assert c.preinput_active
c._preinput_done.wait(9)
c.mark_preinput_run_settled()
print('NEXT_TEXT:'+repr(c.finish_preinput()),flush=True)
print('RECORD_INDEX:'+str(c.record_views['sid'].index),flush=True)
print('COOKED>',flush=True)
print('ECHO:'+input(),flush=True)
"""
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", code], cwd=tmp_path, env=env,
        stdin=slave, stdout=slave, stderr=slave,
    )
    seen = bytearray()

    def receive(needle: bytes, timeout: float = 7.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in seen and time.monotonic() < deadline:
            if select.select([master], [], [], .06)[0]:
                try:
                    seen.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in seen, seen.decode(errors="replace")[-1300:]

    try:
        receive("你".encode())
        os.write(master, b"\x18o")  # Ctrl+X then o, in active-run preinput only
        receive(b"LFL transcript")
        receive(b"browse-only-history")
        os.write(master, b"q")  # close viewer; should restore the original draft
        receive("保留草稿".encode())
        os.write(master, b"\r")
        receive("NEXT_TEXT:'保留草稿 123'".encode())
        receive(b"RECORD_INDEX:0")
        receive(b"COOKED>")
        os.write(master, b"ack\r")
        receive(b"ECHO:ack")
        process.wait(timeout=3)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == saved
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)
