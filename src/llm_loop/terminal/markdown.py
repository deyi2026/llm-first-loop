"""Markdown rendering is a display projection; exact content stays in session/export."""
from __future__ import annotations

import sys

from llm_loop.runtime.resolver import legacy_env_snapshot
from llm_loop.terminal.text import safe_text


def render_markdown(text: str, width: int = 100, plain: bool = False) -> None:
    if plain or not sys.stdout.isatty():
        print(safe_text(text))
        return
    try:
        from rich.console import Console
        from rich.markdown import Markdown
    except ImportError:
        print(safe_text(text))
        return
    no_color = bool(legacy_env_snapshot().get("NO_COLOR"))
    Console(width=min(width, Console().width), markup=False, no_color=no_color).print(
        Markdown(safe_text(text))
    )


class IncrementalMarkdown:
    """TTY-only projection of completed blocks; raw deltas stay authoritative.

    Only the CLI input owner calls these methods. Never start a competing Rich
    Live loop or redraw scrollback behind prompt_toolkit's input compositor.
    Incomplete blocks fall back to raw text after a bounded idle interval;
    already printed bytes are never replayed just to add formatting.
    """

    BLOCK_LIMIT = 8192
    IDLE_SECONDS = 0.15

    def __init__(self, width: int = 100):
        import time

        self.width = width
        self._lines: list[str] = []
        self._partial = ""
        self._fence: str | None = None
        self._raw_paragraph = False
        self._pending_since: float | None = None
        self._clock = time.monotonic

    @staticmethod
    def _raw(text: str) -> None:
        if text:
            print(safe_text(text), end="", flush=True)

    def _rich(self, text: str) -> None:
        if text:
            try:
                render_markdown(text, width=self.width)
            except Exception:  # noqa: BLE001 - display must not break the owned run
                self._raw(text)

    def _flush_stable(self) -> None:
        if self._lines:
            self._rich("".join(self._lines))
            self._lines.clear()
        self._pending_since = None

    def _take_line(self, line: str) -> None:
        stripped = line.strip()
        if self._fence is not None:
            self._raw(line)
            if stripped.startswith(self._fence) and stripped.strip(self._fence[0]) == "":
                self._fence = None
                self._pending_since = None
            return
        if self._raw_paragraph:
            self._raw(line)
            if stripped.startswith(("```", "~~~")):
                # A fenced block can immediately follow a paragraph that was
                # emitted raw to meet the latency budget (without a blank line).
                self._fence = stripped[:3]
                self._raw_paragraph = False
                self._pending_since = None
            elif not stripped:
                self._raw_paragraph = False
                self._pending_since = None
            return
        if stripped.startswith(("```", "~~~")):
            self._flush_stable()
            self._fence = stripped[:3]
            self._raw(line)
            return
        if line.lstrip().startswith("# ") or line.lstrip().startswith("## "):
            self._flush_stable()
            self._rich(line)
            return
        self._lines.append(line)
        if not stripped:
            self._flush_stable()

    def feed(self, fragment: str) -> None:
        if not fragment:
            return
        if self._pending_since is None:
            self._pending_since = self._clock()
        self._partial += fragment
        while "\n" in self._partial:
            current, self._partial = self._partial.split("\n", 1)
            self._take_line(current + "\n")
        # Completing a heading/paragraph may reset its timer while a following
        # partial line is already present in this same provider delta.
        if (self._partial or self._lines) and self._pending_since is None:
            self._pending_since = self._clock()
        if len(self._partial) + sum(map(len, self._lines)) > self.BLOCK_LIMIT:
            self._flush_partial()
        else:
            self.flush_due()

    def _flush_partial(self) -> None:
        if self._lines:
            self._raw("".join(self._lines))
            self._lines.clear()
        if self._partial:
            self._raw(self._partial)
            self._partial = ""
        self._raw_paragraph = self._fence is None
        self._pending_since = None

    def flush_before_status(self) -> None:
        """Preserve visible event order before emitting a tool status to stderr."""
        if self._partial or self._lines:
            self._flush_partial()

    def flush_due(self) -> None:
        if (self._pending_since is not None
                and self._clock() - self._pending_since >= self.IDLE_SECONDS):
            self._flush_partial()

    def finish(self) -> None:
        if self._fence is not None or self._raw_paragraph:
            self._flush_partial()
        else:
            self._lines.append(self._partial)
            self._partial = ""
            self._flush_stable()
        self._raw_paragraph = False
        self._fence = None
