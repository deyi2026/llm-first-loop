"""Mechanical Browser target identity helpers.

Perception uses a private page token namespace (``target:<raw CDP target id>``)
for page/document generation tracking. ActionRef dispatch authority, however, is
bound to the exact raw CDP target id exposed by ``/json/list``. This module owns
the narrow representation bridge and digest so issuance and actuation cannot
drift independently.
"""

from __future__ import annotations

import hashlib

_BROWSER_TARGET_PAGE_TOKEN_PREFIX = "target:"


def raw_browser_target_id_from_page_token(page_token: str) -> str:
    """Return the exact raw target id represented by a private perception token.

    Real CDP capture wraps target ids with ``target:``. Historical deterministic
    fixtures use opaque non-prefixed page tokens; preserve those byte-for-byte so
    the helper does not broaden into semantic normalization.
    """
    token = str(page_token or "")
    if not token or token != token.strip():
        raise ValueError("Browser page token must be non-empty and whitespace-exact")
    if not token.startswith(_BROWSER_TARGET_PAGE_TOKEN_PREFIX):
        return token
    raw_target_id = token[len(_BROWSER_TARGET_PAGE_TOKEN_PREFIX) :]
    if not raw_target_id or raw_target_id != raw_target_id.strip():
        raise ValueError("Browser target page token is missing an exact raw target id")
    return raw_target_id


def browser_target_id_sha256(raw_target_id: str) -> str:
    """Digest one exact raw Browser/CDP target id without search or normalization."""
    target_id = str(raw_target_id or "")
    if not target_id or target_id != target_id.strip():
        raise ValueError("Browser target id must be non-empty and whitespace-exact")
    return hashlib.sha256(target_id.encode("utf-8")).hexdigest()
