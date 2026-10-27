"""M2-A B6 (DESIGN-20261027 §7.3.5): session-fenced download contract.

Pure helpers shared by the cdp actuator (state recording) and the perceive
wait layer (completion judgment + receipt facts). The only I/O is reading a
downloaded file to compute receipt facts - this module never writes, moves,
or deletes anything (the browser itself writes into the fenced dir).
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any


def session_download_dir(root: str, session_id: str) -> str:
    """Deterministic per-session download dir under the engine data root.

    Mirrors the receipt-store fencing shape (<root>/<sha256(session)>/...),
    so every session's downloads are fenced under data_dir and never share a
    directory with another session's files.
    """
    digest = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()
    return os.path.join(os.path.realpath(str(root)), digest, "downloads")


def download_path_policy_error(download_dir: str | None, filename: Any) -> str | None:
    """realpath containment for a browser-suggested filename; None = accepted.

    The filename comes from Page.downloadWillBegin (page-controlled data):
    '../' traversal and symlink escapes must reject with the design-book
    path_not_allowed code BEFORE any fact is reported. An unconfigured dir is
    a deterministic contract failure, not a silent pass.
    """
    if not isinstance(filename, str) or not filename.strip():
        return "download_filename_invalid"
    if not download_dir:
        return "download_dir_unconfigured"
    fenced = os.path.realpath(str(download_dir))
    target = os.path.realpath(os.path.join(fenced, filename))
    if target != fenced and not target.startswith(fenced + os.sep):
        return "path_not_allowed"
    return None


def download_facts(download_dir: str, filename: str) -> dict[str, Any]:
    """Receipt facts for a completed download: path/size/sha256 (+readable).

    Facts degrade to None on read failure - the wait layer reports what was
    actually verifiable, never a fabricated digest.
    """
    path = os.path.realpath(os.path.join(os.path.realpath(str(download_dir)), str(filename)))
    facts: dict[str, Any] = {"path": path, "size": None, "sha256": None, "readable": False}
    try:
        if os.path.isfile(path):
            facts["size"] = os.path.getsize(path)
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            facts["sha256"] = digest.hexdigest()
            facts["readable"] = True
    except OSError:
        pass
    return facts


_DOWNLOAD_FALLBACK_STABLE_S = 0.2


def download_wait_verdict(
    state: dict[str, Any],
    expected: str,
    *,
    size_samples: dict[str, tuple[float, int]] | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """M2-A B6 (§7.3.5): one polling-step judgment; None = keep waiting.

    Completion ladder for expected="completed":
      1. Page.downloadProgress.state == "completed" (completed_by=event);
      2. fallback: file exists, no .crdownload suffix, and the size matched
         across two samples >=200ms apart (completed_by=filesystem_stable).
    expected="failed": satisfied when the event state is canceled.
    A recorded policy_error (../ or symlink escape) fails DETERMINISTICALLY
    with path_not_allowed - no fact is ever reported for a rejected path.
    ``size_samples`` maps guid -> (monotonic timestamp, size) and is updated
    in place by the fallback ladder across poll iterations.
    """
    if expected not in {"completed", "failed"}:
        return {"status": "failed", "reason": "download_expected_invalid"}
    downloads = state.get("downloads")
    if not isinstance(downloads, dict) or not downloads:
        return None
    entry = downloads[next(reversed(list(downloads)))]  # latest recorded download
    base = {"schema": "smc.browser_download_wait.v0.1", "expected": expected, "download": entry}
    policy_error = entry.get("policy_error")
    if isinstance(policy_error, str) and policy_error:
        return {**base, "result": "rejected", "reason": policy_error}
    event_state = str(entry.get("state") or "")
    if expected == "failed":
        if event_state in {"canceled", "failed"}:
            return {**base, "result": "satisfied", "completed_by": "Page.downloadProgress"}
        return None
    if event_state == "completed":
        return _completed_verdict(state, entry, "Page.downloadProgress")
    if event_state == "inprogress":
        # NOT ``size_samples or {}``: an empty-but-carried dict IS the
        # caller's cross-iteration sample store (a falsy-dict copy bug).
        samples = {} if size_samples is None else size_samples
        return _filesystem_stable_verdict(state, entry, samples, now)
    return None


def _completed_verdict(
    state: dict[str, Any], entry: dict[str, Any], completed_by: str
) -> dict[str, Any]:
    download_dir = str(state.get("download_dir") or "")
    facts = download_facts(download_dir, str(entry.get("filename") or "")) if download_dir else {}
    return {
        "schema": "smc.browser_download_wait.v0.1",
        "expected": "completed",
        "result": "satisfied",
        "completed_by": completed_by,
        "download": entry,
        **({"facts": facts} if facts else {}),
    }


def _filesystem_stable_verdict(
    state: dict[str, Any],
    entry: dict[str, Any],
    size_samples: dict[str, tuple[float, int]],
    now: float | None,
) -> dict[str, Any] | None:
    """§7.3.5 fallback: exists + no .crdownload + size stable >=200ms apart."""
    download_dir = str(state.get("download_dir") or "")
    filename = str(entry.get("filename") or "")
    if not download_dir or not filename or filename.endswith(".crdownload"):
        return None
    path = os.path.join(download_dir, filename)
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    stamp = time.monotonic() if now is None else now
    previous = size_samples.get(str(entry.get("guid") or filename))
    size_samples[str(entry.get("guid") or filename)] = (stamp, size)
    if previous is not None and stamp - previous[0] >= _DOWNLOAD_FALLBACK_STABLE_S and size == previous[1]:
        return _completed_verdict(state, entry, "filesystem_stable")
    return None

