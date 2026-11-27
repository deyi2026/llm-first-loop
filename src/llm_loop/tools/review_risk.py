"""Conservative shadow classification of the actual frozen push commit range.

This module is observation only: no review permit, merge permission or PASS.
Unknown surfaces and incomplete evidence are high risk. A future trusted
consumer must independently recompute against the actual remote base and SHA.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

_POLICY = "review-risk-shadow-v1"
_OID = re.compile(r"[0-9a-f]{40}\Z")
_LOW = frozenset({"README.md"})
_MEDIUM = frozenset({
    "webui/src/tokens/app.css", "webui/src/tokens/theme.css",
    "webui/src/tokens/conversation.css", "webui/src/components/layout/video-panel.css",
    "src/llm_loop/web/session_stats_cache.py", "src/llm_loop/introspection/event_scan_cache.py",
    "src/llm_loop/llm/pool.py",
})
_SENSITIVE = re.compile(
    r"auth|permission|approval|review|secret|credential|api.?key|token|sandbox|"
    r"privileg|scope|lease|signatur|gate|privacy|allowlist|denylist|eval\s*\(|exec\s*\(|"
    r"subprocess|url\s*\(|@import|display\s*:\s*none|visibility\s*:\s*hidden", re.I,
)


def _regular_modified_paths(raw: bytes) -> set[str]:
    fields = raw.split(b"\0")
    if not fields or fields[-1] != b"" or len(fields) % 2 != 1:
        raise ValueError("raw_diff_invalid")
    paths = set()
    for meta, name in zip(fields[0:-1:2], fields[1:-1:2], strict=True):
        # Only ordinary, non-executable files modified in place are candidates.
        parts = meta.split()
        if len(parts) != 5 or parts[0:2] != [b":100644", b"100644"] or parts[4] != b"M":
            raise ValueError("nonregular_or_structural_change")
        path = name.decode("utf-8", errors="strict")
        if not path or any(ord(c) < 32 for c in path) or path in paths:
            raise ValueError("ambiguous_path")
        paths.add(path)
    return paths


def classify_commit_risk(git: Callable[..., bytes], root: Path, base: str, candidate: str) -> dict[str, Any]:
    """Use exact commit objects, not an author's label or a mutable local ref."""
    result: dict[str, Any] = {
        "policy": _POLICY, "mode": "shadow_only", "base_sha": base,
        "candidate_sha": candidate, "tier": "high", "reason": "unknown",
        "review_required": True, "release_qualified": False,
    }
    if not _OID.fullmatch(base) or not _OID.fullmatch(candidate) or base == candidate:
        return {**result, "reason": "unbound_or_empty_range"}
    try:
        git(root, "merge-base", "--is-ancestor", base, candidate)
        commits = git(root, "rev-list", "--max-count=33", f"{base}..{candidate}").splitlines()
        if not 1 <= len(commits) <= 32 or git(root, "rev-list", "--merges", "--max-count=1", f"{base}..{candidate}").strip():
            return {**result, "reason": "complex_history"}
        paths = _regular_modified_paths(git(root, "diff", "--raw", "-z", "--no-renames", base, candidate, "--"))
        if not paths or len(paths) > 16 or not paths <= (_LOW | _MEDIUM):
            return {**result, "reason": "protected_or_unclassified_path", "path_count": len(paths)}
        history = git(root, "log", "--format=", "--name-only", "-z", "--no-renames", f"{base}..{candidate}", "--")
        historical_paths = {p.decode("utf-8", errors="strict") for p in history.split(b"\0") if p}
        if historical_paths != paths:
            return {**result, "reason": "history_not_equal_to_final_delta"}
        # Examine all intermediate patches, not just the final tree. Binary and
        # sensitive changes are high; never echo changed lines in the receipt.
        patch = git(root, "log", "--format=", "-p", "--no-ext-diff", "--no-textconv",
                    "--no-renames", "--unified=0", f"{base}..{candidate}", "--").decode("utf-8", errors="strict")
        if any(marker in patch for marker in ("Binary files ", "GIT binary patch", "old mode ", "new mode ", "new file mode ", "deleted file mode ")) or any(
            _SENSITIVE.search(line[1:]) for line in patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ):
            return {**result, "reason": "sensitive_or_binary_delta"}
        tier = "low" if paths <= _LOW else "medium"
        return {**result, "tier": tier, "reason": "bounded_known_surface", "path_count": len(paths)}
    except (OSError, ValueError, RuntimeError, UnicodeError, subprocess.TimeoutExpired):
        return {**result, "reason": "incomplete_or_unclassifiable_evidence"}
