"""Restore the caller's terminal modes on every composer exit."""
from __future__ import annotations

import os
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
        before = termios.tcgetattr(fd)
    except (OSError, ValueError, termios.error):
        yield
        return
    try:
        yield
    finally:
        try:
            # Also restore transient PENDIN changes left by raw/cooked transitions
            # on macOS; do not flush pending input or alter the caller's flags.
            termios.tcsetattr(fd, termios.TCSANOW, before)
        except termios.error:
            print("[terminal closed] mode restoration could not be observed.", file=sys.stderr)
