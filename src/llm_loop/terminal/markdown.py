"""Markdown rendering is a display projection; exact content stays in session/export."""
from __future__ import annotations

import sys

from llm_loop.terminal.presentation import safe_text


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
    Console(width=min(width, Console().width), markup=False).print(Markdown(safe_text(text)))
