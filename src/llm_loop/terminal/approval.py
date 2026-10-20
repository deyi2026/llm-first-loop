"""Marshal the existing native approval callback to the CLI input owner."""
from __future__ import annotations

import queue
import signal
import sys
import threading
from dataclasses import dataclass, field

from llm_loop.terminal.presentation import safe_text
from llm_loop.terminal.state import saved_terminal


@dataclass
class Approval:
    tool: str
    arguments: str
    ready: threading.Event = field(default_factory=threading.Event)
    accepted: bool = False


class ApprovalBridge:
    def __init__(self):
        self.pending = queue.Queue()
        self.closed = threading.Event()
        self.interrupt: threading.Event | None = None

    def __call__(self, tool: str, arguments: str) -> bool:
        if not sys.stdin.isatty() or self.closed.is_set():
            return False
        item = Approval(tool, arguments)
        if threading.current_thread() is threading.main_thread():
            return self._ask(item) and not self.closed.is_set()
        self.pending.put(item)
        while not item.ready.wait(0.1):
            if self.closed.is_set():
                return False
        return item.accepted and not self.closed.is_set()

    def service(self) -> None:
        try:
            item = self.pending.get_nowait()
        except queue.Empty:
            return
        try:
            # A late confirmation after the input owner closes is not an
            # approval. The original request remains denied once closed.
            item.accepted = self._ask(item) and not self.closed.is_set()
        finally:
            item.ready.set()

    def _ask(self, item: Approval) -> bool:
        print(f"\n[approval — deny by default]\ntool: {safe_text(item.tool)}\n"
              f"arguments (complete):\n{safe_text(item.arguments)}", file=sys.stderr, flush=True)
        previous = signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            # No raw tool text is a prompt_toolkit formatting string.
            try:
                from prompt_toolkit import prompt
                from prompt_toolkit.key_binding import KeyBindings
            except ImportError:
                return input("Approve exactly this action? [y/N]: ").strip().lower() in {"y", "yes"}
            keys = KeyBindings()

            @keys.add("escape")
            def deny(event):
                event.app.exit(result="no")

            with saved_terminal():
                answer = prompt("Approve exactly this action? [y/N; Esc denies]: ", key_bindings=keys)
            return answer.strip().lower() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            if self.interrupt is not None:
                self.interrupt.set()
            return False
        finally:
            signal.signal(signal.SIGINT, previous)

    def close(self) -> None:
        self.closed.set()
        while True:
            try:
                item = self.pending.get_nowait()
                item.ready.set()
            except queue.Empty:
                break
