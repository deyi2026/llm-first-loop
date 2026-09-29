"""Shared wire-protocol symbols for the ChatGPT Web provider pair.

Leaf module (R9-P2-06a cycle guard): ``chatgpt_web`` and ``chatgpt_transport``
both consume these symbols, so they live here and neither module imports the
other at module scope. ``chatgpt_web`` re-exports them for backward
compatibility; importers should treat this module as the canonical home.
"""

from __future__ import annotations

MODEL_PROTOCOL = "lfl-model/0.1"
CHATGPT_WEB_PROVIDER_ID = "chatgpt-web"


class ChatGPTModelProtocolError(RuntimeError):
    """The ChatGPT transport returned an invalid provider response."""
