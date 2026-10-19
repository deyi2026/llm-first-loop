"""T08/T18: live changes coexist with an open real alternate-screen viewer."""
from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY required")


def test_t08_live_message_count_and_stream_events_keep_draft_and_tty(tmp_path: Path) -> None:
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    saved = termios.tcgetattr(slave)
    repo = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
               PYTHONPATH=str(repo / "src"))
    script = """
import threading, time
from pathlib import Path
from llm_loop.llm.client import StreamDelta
from llm_loop.terminal.editor import Composer
from llm_loop.terminal.presentation import Presenter
from llm_loop.terminal.settings import UISettings

raw={'messages':[{'role':'user','content':'old record'}]}
c=Composer(UISettings(),Path.cwd())
c.draft='not a model message'
c.record_source=lambda sid: raw
presenter=Presenter(plain=True)
presenter.activity_hook=lambda: c.note_stream_update('s')

def writer():
    start=time.monotonic()
    while c._viewer_app is None and time.monotonic()-start < 4:
        time.sleep(.025)
    time.sleep(.6)
    raw['messages'].append({'role':'assistant','content':'live persisted message'})
    for _ in range(10_000):
        presenter.delta(StreamDelta(text=''))
    print('STREAM_FINISHED_10000', flush=True)

thread=threading.Thread(target=writer,daemon=True)
thread.start()
print('LIVE_VIEW_READY',flush=True)
print(c.show_records('s',['full']),flush=True)
thread.join(3)
print('DRAFT:'+repr(c.draft),flush=True)
print('RAWCOUNT:'+str(len(raw['messages'])),flush=True)
ans=input('COOKED> ')
print('ECHO:'+ans,flush=True)
"""
    proc = subprocess.Popen(
        [sys.executable, "-B", "-c", script], cwd=tmp_path,
        stdin=slave, stdout=slave, stderr=slave, env=env,
    )
    output = bytearray()

    def receive(needle: bytes, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.08)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")[-1300:]

    try:
        receive(b"LFL transcript")
        receive(b"+1 saved", 7)
        receive(b"+10000 live stream updates", 7)
        os.write(master, b"g")
        receive(b"live persisted message")
        os.write(master, b"q")
        receive(b"RAWCOUNT:2")
        receive(b"COOKED> ")
        os.write(master, b"ok\r")
        receive(b"ECHO:ok")
        proc.wait(timeout=3)
        assert proc.returncode == 0
        assert b"not a model message" in output
        assert termios.tcgetattr(slave) == saved
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        os.close(master)
        os.close(slave)
