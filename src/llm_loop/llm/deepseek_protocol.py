"""Shared wire-protocol symbols for the DeepSeek Web provider pair.

Leaf module (R9-P2-06a cycle guard): ``deepseek_web`` and ``deepseek_transport``
both consume these symbols, so they live here and neither module imports the
other at module scope. ``deepseek_web`` re-exports them for backward
compatibility; importers should treat this module as the canonical home.
"""

from __future__ import annotations

MODEL_PROTOCOL = "lfl-model/0.1"
DEEPSEEK_WEB_PROVIDER_ID = "deepseek-web"


class DeepSeekModelProtocolError(RuntimeError):
    """The DeepSeek Web surface returned an invalid LFL provider response."""
