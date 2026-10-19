"""T04 regression: IME-safe multiline send needs no modifier-key delivery."""
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
    ("payload", "result"),
    [
        ("你好", "你好"),
        ("正文一\n/send-not-command\n第二行", "正文一\n/send-not-command\n第二行"),
        ("s你好", "s你好"),  # regression: a literal s must not be silently eaten
    ],
)
def test_multiline_text_send_works_after_ime_candidate_without_ctrl(
    tmp_path: Path, payload: str, result: str,
) -> None:
    """A real POSIX PTY: Enter never submits an IME composition; /send does."""
    pytest.importorskip("prompt_toolkit")
    import pty
    import termios

    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        TERM="xterm-256color",
        PROMPT_TOOLKIT_NO_CPR="1",
        PYTHONPATH=str(root / "src"),
    )
    script = (
        "import json; from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(multiline=True),Path.cwd()); "
        "s=c.read('ime-t04','glm/glm-5.3'); "
        "print('RESULT:'+json.dumps(s,ensure_ascii=False),flush=True); "
        "print('COOKED>',flush=True); "
        "echo=input(); print('ECHO:'+echo,flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script],
        cwd=tmp_path, env=env, stdin=slave, stdout=slave, stderr=slave,
    )
    observed = bytearray()

    def receive(needle: bytes, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in observed and time.monotonic() < deadline:
            if select.select([master], [], [], 0.07)[0]:
                try:
                    observed.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in observed, observed.decode(errors="replace")[-1400:]

    try:
        receive("你 >".encode())
        # A bracketed paste is an IME surrogate, not physical IME qualification.
        os.write(master, b"\x1b[200~" + payload.encode() + b"\x1b[201~")
        os.write(master, b"\r")  # candidate confirmation / regular Enter = newline
        time.sleep(0.15)
        assert b"RESULT:" not in observed
        os.write(master, b"/send\r")
        import json

        receive(("RESULT:" + json.dumps(result, ensure_ascii=False)).encode())
        receive(b"COOKED>")
        os.write(master, b"ack\r")
        receive(b"ECHO:ack")
        process.wait(timeout=4)
        assert process.returncode == 0
        assert termios.tcgetattr(slave) == original
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_no_body_does_not_submit_on_first_send_line(tmp_path: Path) -> None:
    """A literal first-line /send must not silently send an empty model turn."""
    pytest.importorskip("prompt_toolkit")
    import pty

    master, slave = pty.openpty()
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1",
        PYTHONPATH=str(root / "src"),
    )
    script = (
        "from pathlib import Path; "
        "from llm_loop.terminal.editor import Composer; "
        "from llm_loop.terminal.settings import UISettings; "
        "c=Composer(UISettings(multiline=True),Path.cwd()); "
        "print('SENT:'+repr(c.read('s','glm')),flush=True)"
    )
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script], cwd=tmp_path, env=env,
        stdin=slave, stdout=slave, stderr=slave,
    )
    output = bytearray()
    def receive(needle: bytes, timeout: float = 7.0) -> None:
        deadline = time.monotonic() + timeout
        while needle not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.08)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        assert needle in output, output.decode(errors="replace")[-1300:]
    try:
        receive("你 >".encode())
        os.write(master, b"/send\r")
        time.sleep(.15)
        assert b"SENT:" not in output
        os.write(master, b"literal text\r/send\r")
        receive(b"SENT:'/send\\nliteral text'")
        process.wait(timeout=3)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_plain_mode_send_alias_and_escaped_literal(tmp_path: Path, monkeypatch) -> None:
    from llm_loop.terminal.editor import Composer
    from llm_loop.terminal.settings import UISettings

    inputs = iter(["你好", "//send", "."])
    monkeypatch.setattr("builtins.input", lambda *_args: next(inputs))
    composer = Composer(UISettings(multiline=True, plain=True), tmp_path)
    assert composer._plain_read() == "你好\n/send"
    inputs = iter(["继续", "/send"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(inputs))
    assert composer._plain_read() == "继续"
