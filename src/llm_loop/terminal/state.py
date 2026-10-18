"""Restore the caller's terminal modes on every composer exit."""
from __future__ import annotations

import os
import signal
import sys
from contextlib import contextmanager


@contextmanager
def saved_terminal():
    if os.name != "posix" or not sys.stdin.isatty():
        yield
        return
    import termios

    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError, termios.error):
        yield
        return
    before = None

    def restore() -> None:
        if before is None:
            return
        try:
            # Also restore transient PENDIN changes left by raw/cooked transitions
            # on macOS; do not flush pending input or alter the caller's flags.
            termios.tcsetattr(fd, termios.TCSANOW, before)
        except (OSError, termios.error):
            print("[terminal closed] mode restoration could not be observed.", file=sys.stderr)

    previous = signal.getsignal(signal.SIGTERM)
    handler_installed = False
    if previous == signal.SIG_DFL:
        def terminate(signum, _frame):
            restore()
            raise SystemExit(128 + signum)

        try:
            signal.signal(signal.SIGTERM, terminate)
            handler_installed = True
        except ValueError:
            # signal handlers can only be installed by the main thread.
            pass
    try:
        # Install the handler before reading the saved mode. If SIGTERM arrives
        # before this snapshot, the terminal has not been changed and restore is
        # intentionally a no-op; after it, restore has the exact original state.
        before = termios.tcgetattr(fd)
    except (OSError, ValueError, termios.error):
        if handler_installed and signal.getsignal(signal.SIGTERM) is terminate:
            signal.signal(signal.SIGTERM, previous)
        yield
        return
    try:
        yield
    finally:
        restore()
        # Do not overwrite a handler intentionally installed by the body.
        if handler_installed and signal.getsignal(signal.SIGTERM) is terminate:
            signal.signal(signal.SIGTERM, previous)
