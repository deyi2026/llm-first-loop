"""Shared inert terminal text escape, without a presentation/Markdown cycle."""
from __future__ import annotations

import re

# Do not interpret untrusted OSC/DCS/CSI, even across streamed token boundaries.
# Preserve newlines and tabs; exact source remains in session/event storage.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def safe_text(value: object) -> str:
    return _CONTROL.sub(lambda m: f"\\x{ord(m[0]):02x}", str(value))
