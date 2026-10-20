"""Opt-in, read-only alternate-screen transcript viewer for actual TTYs.

The viewer neither acquires an Engine/Provider nor has a submission path. It
reads a snapshot on refresh and keeps the original composer buffer untouched.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

from llm_loop.terminal.presentation import safe_text
from llm_loop.terminal.records import RecordBrowser
from llm_loop.terminal.state import saved_terminal


def open_viewer(
    source: Callable[[], dict],
    browser: RecordBrowser,
    *,
    live_updates: Callable[[], int] | None = None,
    on_app: Callable[[object | None], None] | None = None,
) -> bool:
    """Run a real full-screen viewer; False means the caller must use text mode."""
    import sys

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.patch_stdout import patch_stdout
    except ImportError:
        return False

    state: dict[str, object] = {"at": 0.0, "raw": {"messages": []},
                                "message": "", "exit": False}

    def snapshot(*, force: bool = False) -> dict:
        now = time.monotonic()
        if force or now - cast(float, state["at"]) >= 0.35:
            try:
                data = source()
                if not isinstance(data, dict) or not isinstance(data.get("messages", []), list):
                    raise ValueError("Invalid stored transcript")
                state["raw"] = data
                state["message"] = ""
            except (OSError, ValueError, TypeError) as exc:
                state["message"] = f"[read-only snapshot unavailable: {type(exc).__name__}]"
            state["at"] = now
        return state["raw"]  # type: ignore[return-value]

    keys = KeyBindings()
    app = None

    def content() -> str:
        raw = snapshot()
        try:
            return safe_text(browser.navigate(raw, ["show"]))
        except (ValueError, TypeError, KeyError):
            return "[transcript content unavailable]"

    def header() -> str:
        snapshot()
        updates = int(live_updates()) if live_updates is not None else 0
        return (
            f" LFL transcript · +{browser.new_messages} saved · "
            f"+{updates} live stream updates (not saved messages) · "
            f"{'FOLLOW' if browser.follow_latest else 'PAUSED'} "
        )

    def command(action: str) -> None:
        raw = snapshot(force=True)
        try:
            browser.navigate(raw, [action])
        except ValueError as exc:
            state["message"] = f"[navigation unavailable: {type(exc).__name__}]"
        if app is not None:
            app.invalidate()

    @keys.add("q")
    @keys.add("escape")
    @keys.add("c-c")
    def quit_viewer(event) -> None:
        event.app.exit()

    for key, action in (
        ("j", "next"), ("k", "prev"), ("down", "next"), ("up", "prev"),
        ("n", "page"), ("p", "back"), ("pagedown", "page"), ("pageup", "back"),
        ("l", "right"), ("h", "left"), ("right", "right"), ("left", "left"),
        ("d", "diff"), ("i", "details"), ("c", "content"),
        ("g", "latest"), ("f", "follow"), ("r", "show"),
    ):
        keys.add(key)(lambda event, action=action: command(action))

    layout = Layout(HSplit([
        Window(height=1, content=FormattedTextControl(header), style="reverse"),
        Window(content=FormattedTextControl(content, focusable=True), wrap_lines=False),
        Window(height=1, content=FormattedTextControl(
            lambda: str(state["message"]) or
            " q/Esc exit · j/k record · n/p page · h/l columns · g latest · "
            "f follow · d diff · i details · c content · r refresh "
        ), style="reverse"),
    ]))
    app = Application(layout=layout, key_bindings=keys,
                      full_screen=True, mouse_support=False, erase_when_done=True)
    if on_app:
        on_app(app)
    try:
        with saved_terminal(), patch_stdout():
            app.run()
    finally:
        if on_app:
            on_app(None)
    return True
