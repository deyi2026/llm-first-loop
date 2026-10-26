"""Own a backend process group independently of the worker's lifetime.

The OS pipe closes when the worker dies, including SIGKILL. The guardian retains
the video slot until its child group is terminated and reaped, and handles
cancellation and timeout without a live Web process or worker.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


def supervise(directory: Path, lifeline: int, deadline: float, argv: list[str]) -> int:
    proc = None
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, start_new_session=True)
        while proc.poll() is None:
            if (directory / "cancel").exists():
                print("Video generation cancelled.", file=sys.stderr, flush=True)
                return 130
            if time.monotonic() >= deadline:
                print("Video generation timed out.", file=sys.stderr, flush=True)
                return 124
            readable, _, _ = select.select([lifeline], [], [], 0.2)
            if readable and os.read(lifeline, 1) == b"":
                print("Video worker exited; stopping owned backend.", file=sys.stderr, flush=True)
                return 125
        return proc.returncode or 0
    finally:
        if proc is not None and proc.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


if __name__ == "__main__":
    raise SystemExit(
        supervise(Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), json.loads(sys.argv[4]))
    )
