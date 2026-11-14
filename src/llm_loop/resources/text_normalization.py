"""Pure text normalization primitives shared across planes.

The ONLY definition of the FileService line-ending algorithm (moved from
``llm_loop.workspace.file_service`` verbatim; that module re-exports these
names so existing callers stay source-compatible). ``resources`` (the T1
web budget profile) and ``workspace`` (FileService.edit) MUST share this
exact implementation — two copies would drift apart and silently disagree
on byte-exact edit previews. Living here keeps the kernel import-edge
ratchet intact: ``resources`` stays free of any ``resources->workspace``
edge (workspace is not a kernel plane and may import from resources).
"""

from __future__ import annotations


def detect_line_ending(text: str) -> str:
    """Return CRLF when it is the dominant original newline style, otherwise LF."""
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def normalize_lf(text: str) -> str:
    """Normalize CRLF/CR to LF for content matching only."""
    return text.replace("\r\n", "\n").replace("\r", "\n")
