"""Conservative, read-only baseline impact projection (v1.9 B2).

This module NEVER grants merge, review, R9, or receipt authority.  Local
``origin/main`` is a measured tracking ref, not proof of remote freshness.
Every ambiguous Git/path/worktree observation degrades to ``unknown``.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_RAW = re.compile(rb"^:([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([A-Z])$")
_REGULAR = {b"000000", b"100644", b"100755"}
_MAX_OUTPUT = 256 * 1024


def _git(repo: Path, *args: str) -> tuple[bytes | None, str]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
            capture_output=True, timeout=3, env=env, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None, "git_probe_unavailable"
    if proc.returncode != 0 or len(proc.stdout) > _MAX_OUTPUT:
        return None, "git_probe_failed"
    return proc.stdout, ""


def _sha(raw: object) -> bool:
    return isinstance(raw, str) and bool(_SHA.fullmatch(raw))


def _decode(raw: bytes | None) -> str | None:
    try:
        return raw.decode("utf-8").strip() if raw is not None else None
    except UnicodeDecodeError:
        return None


def probe_main_host(repo_root: str | Path) -> dict[str, Any]:
    """Host-only Git measurement. No caller-provided SHA is trusted."""
    root = Path(repo_root).expanduser().resolve()
    top, err = _git(root, "rev-parse", "--show-toplevel")
    head, head_err = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    main, main_err = _git(root, "rev-parse", "--verify", "origin/main^{commit}")
    top_text, head_text, main_text = _decode(top), _decode(head), _decode(main)
    valid = (
        not (err or head_err or main_err)
        and top_text is not None and Path(top_text).resolve() == root
        and _sha(head_text) and _sha(main_text)
    )
    return {
        "checkout_head": head_text if _sha(head_text) else None,
        "origin_main": main_text if _sha(main_text) else None,
        "selected_main": main_text if valid else None,
        "selected_main_source": "host_local_tracking" if valid else "unknown",
        "source_complete": bool(valid),
        "remote_verified": False,
        "freshness_class": "local_ref_only" if valid else "unknown",
        "repo_root": str(root),
        "observed_at_monotonic": time.monotonic(),
    }


def _safe_path(raw: bytes, repo: Path) -> tuple[str | None, str]:
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, "path_encoding_unverifiable"
    if (
        not path or path.startswith("/") or "\\" in path
        or any(part in ("", ".", "..", ".git") for part in path.split("/"))
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
    ):
        return None, "path_ambiguous"
    # Unknown case-insensitive filesystem and Unicode normalization rules:
    # a path is never called disjoint if its equivalence cannot be proven.
    if not path.isascii() or unicodedata.normalize("NFC", path) != path:
        return None, "path_alias_ambiguous"
    node = repo
    for part in path.split("/"):
        node = node / part
        if node.is_symlink():
            return None, "path_symlink_unverifiable"
    return path, ""


def _diff_paths(repo: Path, base: str, head: str) -> tuple[set[str] | None, str]:
    if not (_sha(base) and _sha(head)):
        return None, "git_ref_unverifiable"
    merges, err = _git(repo, "rev-list", "--merges", f"{base}..{head}")
    if err or merges is None or merges.strip():
        return None, "merge_range_unverifiable"
    raw, err = _git(repo, "diff", "--raw", "-z", "--no-renames", "--abbrev=40", base, head)
    if err or raw is None or (raw and not raw.endswith(b"\0")):
        return None, "path_probe_unverifiable"
    entries = raw[:-1].split(b"\0") if raw else []
    if len(entries) % 2:
        return None, "path_probe_unverifiable"
    paths: set[str] = set()
    for i in range(0, len(entries), 2):
        match = _RAW.fullmatch(entries[i])
        if match is None:
            return None, "path_probe_unverifiable"
        old_mode, new_mode, _, _, change = match.groups()
        if (
            old_mode not in _REGULAR or new_mode not in _REGULAR
            or (old_mode != new_mode and b"000000" not in (old_mode, new_mode))
            or change not in (b"A", b"D", b"M")
        ):
            return None, "file_mode_unverifiable"
        path, reason = _safe_path(entries[i + 1], repo)
        if reason or path is None:
            return None, reason
        paths.add(path)
    numstat, err = _git(repo, "diff", "--numstat", "-z", "--no-renames", base, head)
    if err or numstat is None or (numstat and not numstat.endswith(b"\0")):
        return None, "path_probe_unverifiable"
    num_paths: set[str] = set()
    for item in numstat[:-1].split(b"\0") if numstat else []:
        parts = item.split(b"\t", 2)
        if len(parts) != 3 or not all(part.isdigit() for part in parts[:2]):
            return None, "binary_or_numstat_unverifiable"
        path, reason = _safe_path(parts[2], repo)
        if reason or path is None:
            return None, reason
        num_paths.add(path)
    if paths != num_paths:
        return None, "path_probe_unverifiable"
    if len({path.casefold() for path in paths}) != len(paths):
        return None, "path_alias_ambiguous"
    return paths, ""


def _same_repo_and_clean(repo: Path, worktree_raw: object, expected_head: str) -> str:
    if not isinstance(worktree_raw, str) or not worktree_raw.strip():
        return "worktree_unverified"
    worktree = Path(worktree_raw).expanduser().resolve()
    top, err = _git(worktree, "rev-parse", "--show-toplevel")
    if err or _decode(top) != str(worktree):
        return "worktree_unverified"
    left, left_err = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    right, right_err = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if left_err or right_err or _decode(left) != _decode(right):
        return "worktree_foreign_repo"
    actual, err = _git(worktree, "rev-parse", "HEAD")
    if err or _decode(actual) != expected_head:
        return "lane_head_mismatch"
    dirty, err = _git(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if err or dirty is None:
        return "worktree_status_unverified"
    if dirty:
        return "uncommitted_changes"
    return ""


def _claims_valid(repo: Path, claims: object, paths: set[str]) -> bool:
    if not isinstance(claims, list) or not claims:
        return False
    normalized = []
    for claim in claims:
        if not isinstance(claim, str):
            return False
        raw = claim.rstrip("/")
        try:
            encoded = raw.encode("utf-8", "strict")
        except UnicodeEncodeError:
            return False
        safe, reason = _safe_path(encoded, repo)
        if reason or safe is None:
            return False
        normalized.append((safe, claim.endswith("/")))
    return all(any(p == c or (directory and p.startswith(c + "/"))
                   for c, directory in normalized) for p in paths)


def _aliased_overlap(left: set[str], right: set[str]) -> bool:
    return bool({p.casefold() for p in left} & {p.casefold() for p in right})


def _result(lane: dict, baseline: dict, status: str, reason: str,
            *, changed: set[str] | None = None, overlap: set[str] | None = None,
            verified: bool = False) -> dict[str, Any]:
    next_step = {
        "current": "reverify", "stale_needs_refresh": "refresh_base",
        "affected": "review_contract", "unknown": "hold",
        "carryover_candidate": "reverify",
    }[status]
    return {
        "schema_version": 1,
        "lane_id": lane.get("lane_id"),
        "lane_version": lane.get("version"),
        "lane_head_sha": lane.get("head_sha"),
        "lane_base_main_sha": lane.get("base_main_sha"),
        "baseline": baseline,
        "impact": {
            "status": status,
            "reason_codes": [reason],
            "changed_paths": sorted(changed or ()),
            "overlap_paths": sorted(overlap or ()),
            "git_probes_complete": verified,
            "recommended_next_step": next_step,
        },
        "evidence": {"projection_is_authoritative": False,
                     "git_ref_observed": "origin/main" if baseline.get("source_complete") else None},
    }


def project_baseline_impact(
    repo_root: str | Path, lane: dict, *, caller_main_head: str | None = None,
    peer_lanes: list[dict] | None = None,
) -> dict[str, Any]:
    """Project risk only; never treat caller ``main_head`` as a trusted fact."""
    repo = Path(repo_root).expanduser().resolve()
    baseline = probe_main_host(repo)
    if not isinstance(lane, dict):
        lane = {}

    def unknown(reason: str) -> dict[str, Any]:
        return _result(lane, baseline, "unknown", reason)

    if caller_main_head is not None:
        baseline["caller_main_head_ignored"] = True
        return unknown("main_identity_untrusted")
    if not baseline["source_complete"]:
        return unknown("main_identity_untrusted")
    if not isinstance(lane, dict) or not (_sha(lane.get("head_sha"))
                                          and _sha(lane.get("base_main_sha"))):
        return unknown("lane_sha_invalid")
    if type(lane.get("version")) is not int or lane["version"] < 1:
        return unknown("lane_snapshot_degraded")
    if not isinstance(lane.get("lane_id"), str) or not lane["lane_id"]:
        return unknown("lane_snapshot_degraded")
    main = baseline["selected_main"]
    reason = _same_repo_and_clean(repo, lane.get("worktree"), lane["head_sha"])
    if reason:
        return unknown(reason)
    if not _claims_valid(repo, lane.get("paths"), set()):
        return unknown("paths_undeclared_or_ambiguous")
    if lane["base_main_sha"] == main:
        return _result(lane, baseline, "current", "base_current", verified=True)
    ancestor, err = _git(repo, "merge-base", "--is-ancestor", lane["base_main_sha"], main)
    if err or ancestor is None:
        return unknown("main_diverged_or_missing_history")
    advanced, reason = _diff_paths(repo, lane["base_main_sha"], main)
    if reason or advanced is None:
        return unknown(reason)
    own, reason = _diff_paths(repo, lane["base_main_sha"], lane["head_sha"])
    if reason or own is None:
        return unknown(reason)
    if not _claims_valid(repo, lane.get("paths"), own):
        return unknown("lane_paths_incomplete")
    rechecked, err = _git(repo, "rev-parse", "--verify", "origin/main^{commit}")
    if err or _decode(rechecked) != main:
        return unknown("snapshot_changed")
    overlap = advanced & own
    if overlap:
        return _result(lane, baseline, "affected", "actual_paths_overlap",
                       changed=advanced, overlap=overlap, verified=True)
    if _aliased_overlap(advanced, own):
        return unknown("path_alias_ambiguous")
    contracts = lane.get("contract_changes") or []
    if not isinstance(contracts, list) or not all(isinstance(x, str) for x in contracts):
        return unknown("contract_context_unverified")
    if contracts and peer_lanes is None:
        return unknown("contract_context_unverified")
    for peer in peer_lanes or []:
        if not isinstance(peer, dict) or peer.get("lane_id") == lane["lane_id"]:
            continue
        other = peer.get("contract_changes") or []
        if not isinstance(other, list) or not all(isinstance(x, str) for x in other):
            return unknown("contract_context_unverified")
        if set(contracts) & set(other):
            return _result(lane, baseline, "affected", "contract_same_key_hint",
                           changed=advanced, verified=True)
        if {c.casefold().replace("_", "") for c in contracts} & {
            c.casefold().replace("_", "") for c in other
        }:
            return unknown("contract_alias_ambiguous")
    return _result(lane, baseline, "stale_needs_refresh",
                   "disjoint_paths_need_replay_assessment", changed=advanced,
                   verified=True)


def assess_rebased_carryover(
    repo_root: str | Path, *, old_base: str, old_head: str,
    new_base: str, new_head: str,
) -> dict[str, Any]:
    """Precheck path safety before invoking the existing replay predicate.

    The result is an advisory *candidate*, never a signed verify receipt.
    """
    repo = Path(repo_root).expanduser().resolve()
    args = (old_base, old_head, new_base, new_head)
    if not all(_sha(v) for v in args):
        return {"status": "unknown", "reason": "git_ref_unverifiable"}
    path_sets: list[set[str]] = []
    for base, head in ((old_base, new_base), (old_base, old_head),
                       (new_base, new_head)):
        paths, reason = _diff_paths(repo, base, head)
        if reason or paths is None:
            return {"status": "unknown", "reason": reason}
        path_sets.append(paths)
    advanced, old_lane, new_lane = path_sets
    if _aliased_overlap(advanced, new_lane) or old_lane != new_lane:
        return {"status": "unknown", "reason": "full_reverification_required"}
    ancestor, err = _git(repo, "merge-base", "--is-ancestor", old_base, new_base)
    if err or ancestor is None:
        return {"status": "unknown", "reason": "main_diverged_or_missing_history"}
    from llm_loop.introspection.merge_queue import assess_rebase_replay

    replay = assess_rebase_replay(
        repo, old_base=old_base, old_head=old_head,
        new_base=new_base, new_head=new_head,
    )
    if not replay.get("eligible"):
        return {"status": "unknown", "reason": "full_reverification_required",
                "replay_reason": replay.get("reason")}
    return {"status": "carryover_candidate",
            "reason": "request_existing_issuer_validation",
            "requires_new_head_reviewer": True,
            "verify_receipt_issued": False}
