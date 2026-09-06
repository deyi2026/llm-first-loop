#!/usr/bin/env python3
"""Private cross-agent continuity transport for LFL.

Public code stores private configuration only in local Git config and keeps the
continuity checkout outside the source worktree. Historical handoffs are never
loaded automatically; candidate selection is explicit and mechanically ranked.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 64 * 1024
_SCHEMA = 1
_CONFIG_PREFIX = "lfl.continuity"
_GENERIC_GIT_NAME = "LFL Continuity"
_GENERIC_GIT_EMAIL = "continuity@localhost"

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "authorization_bearer",
        re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    ),
    (
        "credential_assignment",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[^\s,;]+",
            re.IGNORECASE,
        ),
    ),
    ("openai_style_token", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
)


class ContinuityError(RuntimeError):
    pass


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(source_root: Path, *args: str, check: bool = True) -> str:
    proc = _run(("git", *args), cwd=source_root, check=check)
    return proc.stdout.strip()


def source_root_from_cwd(cwd: Path | None = None) -> Path:
    here = (cwd or Path.cwd()).resolve()
    proc = _run(("git", "rev-parse", "--show-toplevel"), cwd=here)
    return Path(proc.stdout.strip()).resolve()


def _config_get(source_root: Path, key: str) -> str:
    proc = _run(("git", "config", "--local", "--get", key), cwd=source_root, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _config_set(source_root: Path, key: str, value: str) -> None:
    try:
        _run(("git", "config", "--local", key, value), cwd=source_root)
    except subprocess.SubprocessError as exc:
        raise ContinuityError("failed to write private continuity local config") from exc


def _project_id(source_root: Path) -> str:
    configured = _config_get(source_root, f"{_CONFIG_PREFIX}.project")
    raw = configured
    if not raw:
        pyproject = source_root / "pyproject.toml"
        try:
            parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = parsed.get("project", {})
            if isinstance(project, dict):
                raw = str(project.get("name", "") or "")
        except (OSError, tomllib.TOMLDecodeError):
            raw = ""
    raw = raw or source_root.name or "project"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.")
    return safe or "project"


def _default_store_path(source_root: Path) -> Path:
    configured_base = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(configured_base).expanduser() if configured_base else Path.home() / ".local" / "share"
    return (base / "lfl" / "continuity" / _project_id(source_root)).resolve()


def _store_path(source_root: Path) -> Path:
    configured = _config_get(source_root, f"{_CONFIG_PREFIX}.path")
    return Path(configured).expanduser().resolve() if configured else _default_store_path(source_root)


def _validate_store_outside_source(source_root: Path, store: Path) -> None:
    try:
        inside = store == source_root or store.is_relative_to(source_root)
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        inside = source_root == store or source_root in store.parents
    if inside:
        raise ContinuityError("continuity store must live outside the source worktree")


def _validate_remote(remote: str) -> None:
    if not remote:
        return
    if any(ch.isspace() for ch in remote):
        raise ContinuityError("private remote must not contain whitespace")
    if remote.startswith(("http://", "https://")):
        parsed = urlsplit(remote)
        if parsed.username is not None or parsed.password is not None:
            raise ContinuityError("credentialed HTTP(S) remote URLs are forbidden")
    if "://" in remote:
        parsed = urlsplit(remote)
        if parsed.password is not None:
            raise ContinuityError("remote URL must not embed a password or token")


def _configured_remote(source_root: Path) -> str:
    remote = _config_get(source_root, f"{_CONFIG_PREFIX}.remote")
    _validate_remote(remote)
    return remote


def _ensure_repo_identity(store: Path) -> None:
    for key, value in (("user.name", _GENERIC_GIT_NAME), ("user.email", _GENERIC_GIT_EMAIL)):
        proc = _run(("git", "config", "--local", "--get", key), cwd=store, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            _run(("git", "config", "--local", key, value), cwd=store)


def _ensure_origin(store: Path, remote: str) -> None:
    if not remote:
        return
    proc = _run(("git", "remote", "get-url", "origin"), cwd=store, check=False)
    try:
        if proc.returncode == 0:
            current = proc.stdout.strip()
            if current != remote:
                _run(("git", "remote", "set-url", "origin", remote), cwd=store)
        else:
            _run(("git", "remote", "add", "origin", remote), cwd=store)
    except subprocess.SubprocessError as exc:
        raise ContinuityError("failed to configure private continuity origin") from exc


def ensure_store(source_root: Path) -> Path:
    store = _store_path(source_root)
    _validate_store_outside_source(source_root, store)
    remote = _configured_remote(source_root)
    store.parent.mkdir(parents=True, exist_ok=True)
    # Store creation/clone is itself a shared mutation. Serialize it with the
    # same external lock used for later Git operations so two agents starting
    # from an empty machine cannot race on `git init` / `git clone`.
    with store_lock(store):
        if (store / ".git").exists():
            _ensure_origin(store, remote)
            _ensure_repo_identity(store)
            return store

        if remote:
            proc = _run(("git", "clone", "--quiet", remote, str(store)), cwd=store.parent, check=False)
            if proc.returncode != 0:
                raise ContinuityError(
                    "private continuity remote could not be cloned; configure once while it is reachable"
                )
        else:
            store.mkdir(parents=True, exist_ok=True)
            _run(("git", "init", "-q", "-b", "main"), cwd=store)
        _ensure_repo_identity(store)
    return store


@contextmanager
def store_lock(store: Path) -> Iterator[None]:
    lock_path = store.parent / f".{store.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _secret_findings(text: str) -> list[str]:
    findings = [name for name, pattern in _SECRET_PATTERNS if pattern.search(text)]
    for match in re.finditer(r"https?://[^\s)>'\"]+", text, re.IGNORECASE):
        parsed = urlsplit(match.group(0))
        if parsed.username is not None or parsed.password is not None:
            findings.append("credentialed_url")
            break
    return sorted(set(findings))


def _read_handoff_input(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContinuityError("unable to read private handoff input file") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise ContinuityError(f"handoff input exceeds {MAX_INPUT_BYTES} bytes")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuityError(f"handoff input must be UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContinuityError("handoff input root must be a JSON object")

    required_strings = ("workstream_id", "objective")
    optional_strings = ("goal_id", "agent", "suggested_next_step")
    list_fields = (
        "verified_facts",
        "completed",
        "decisions",
        "open_questions",
        "affected_paths",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ContinuityError(f"handoff input requires non-empty string: {key}")
    for key in optional_strings:
        if key in data and not isinstance(data[key], str):
            raise ContinuityError(f"handoff field must be a string: {key}")
    for key in list_fields:
        value = data.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ContinuityError(f"handoff field must be a list of strings: {key}")
        data[key] = value
    for path_value in data.get("affected_paths", []):
        p = Path(path_value)
        if p.is_absolute() or ".." in p.parts:
            raise ContinuityError("affected_paths must contain repository-relative paths only")

    findings = _secret_findings(raw.decode("utf-8", errors="replace"))
    if findings:
        raise ContinuityError("handoff input rejected by secret scan: " + ", ".join(findings))
    return data


def _working_tree_facts(source_root: Path) -> dict[str, Any]:
    head = _git(source_root, "rev-parse", "HEAD")
    branch = _git(source_root, "branch", "--show-current") or "DETACHED"
    status = _git(source_root, "status", "--porcelain=v1", "-z")
    records = [record for record in status.split("\0") if record]
    untracked_count = sum(1 for record in records if record.startswith("??"))
    tracked_dirty_count = len(records) - untracked_count

    digest = hashlib.sha256()
    diff = _run(("git", "diff", "--binary", "HEAD", "--"), cwd=source_root).stdout
    digest.update(diff.encode("utf-8", errors="surrogateescape"))
    digest.update(status.encode("utf-8", errors="surrogateescape"))

    untracked = _git(source_root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_paths = [item for item in untracked.split("\0") if item]
    hashed_untracked = 0
    for rel in untracked_paths[:200]:
        proc = _run(("git", "hash-object", "--no-filters", "--", rel), cwd=source_root, check=False)
        if proc.returncode == 0:
            digest.update(rel.encode("utf-8", errors="surrogateescape"))
            digest.update(proc.stdout.strip().encode("ascii", errors="ignore"))
            hashed_untracked += 1

    remote_refs_raw = _git(
        source_root,
        "branch",
        "-r",
        "--contains",
        head,
        "--format=%(refname:short)",
        check=False,
    )
    remote_ref_count = len([line for line in remote_refs_raw.splitlines() if line.strip()])
    clean = not records
    portability = "complete" if clean and remote_ref_count > 0 else "metadata_only"
    return {
        "source_head": head,
        "source_branch": branch,
        "source_clean": clean,
        "tracked_dirty_count": tracked_dirty_count,
        "untracked_count": untracked_count,
        "working_tree_fingerprint_sha256": digest.hexdigest(),
        "fingerprint_untracked_hashed": hashed_untracked,
        "fingerprint_untracked_truncated": len(untracked_paths) > hashed_untracked,
        "source_remote_ref_count_containing_head": remote_ref_count,
        "source_portability": portability,
        "source_portability_evidence": (
            "local_remote_tracking_ref" if portability == "complete" else "insufficient"
        ),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _handoff_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{secrets.token_hex(4)}"


def _safe_id(value: str, *, field: str) -> str:
    value = value.strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ContinuityError(f"{field} must match [A-Za-z0-9._-]+")
    return value


def _manifest_and_markdown(
    source_root: Path,
    input_data: dict[str, Any],
    handoff_id: str,
) -> tuple[dict[str, Any], str]:
    workstream = _safe_id(input_data["workstream_id"], field="workstream_id")
    goal_id = input_data.get("goal_id", "").strip()
    if goal_id:
        _safe_id(goal_id, field="goal_id")
    facts = _working_tree_facts(source_root)
    manifest: dict[str, Any] = {
        "schema": _SCHEMA,
        "handoff_id": handoff_id,
        "project_id": _project_id(source_root),
        "workstream_id": workstream,
        "goal_id": goal_id,
        "agent": input_data.get("agent", "").strip(),
        "created_at": _now(),
        **facts,
    }

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- (none recorded)"

    affected = input_data.get("affected_paths", [])
    wip_lines = [
        f"- source_head: `{facts['source_head']}`",
        f"- source_branch: `{facts['source_branch']}`",
        f"- source_clean: `{str(facts['source_clean']).lower()}`",
        f"- source_portability: `{facts['source_portability']}`",
        f"- tracked_dirty_count: `{facts['tracked_dirty_count']}`",
        f"- untracked_count: `{facts['untracked_count']}`",
        f"- working_tree_fingerprint_sha256: `{facts['working_tree_fingerprint_sha256']}`",
    ]
    if affected:
        wip_lines.append("- affected_paths:")
        wip_lines.extend(f"  - `{path}`" for path in affected)

    next_step = input_data.get("suggested_next_step", "").strip() or "(none recorded)"
    markdown = f"""# Continuity handoff {handoff_id}

> Historical handoff only. This file is not a current instruction. Re-verify current Git/runtime state before acting.

## Objective

{input_data['objective'].strip()}

## Verified Facts

{bullets(input_data.get('verified_facts', []))}

## Completed

{bullets(input_data.get('completed', []))}

## Decisions

{bullets(input_data.get('decisions', []))}

## WIP State

{chr(10).join(wip_lines)}

## Open Questions

{bullets(input_data.get('open_questions', []))}

## Suggested Next Step (historical, non-authoritative)

{next_step}
"""
    combined = json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n" + markdown
    findings = _secret_findings(combined)
    if findings:
        raise ContinuityError("rendered handoff rejected by secret scan: " + ", ".join(findings))
    return manifest, markdown


def _commit_paths(store: Path, paths: Sequence[Path], message: str) -> str:
    rels = [str(path.relative_to(store)) for path in paths]
    _run(("git", "add", "--", *rels), cwd=store)
    staged = _run(("git", "diff", "--cached", "--name-only", "--"), cwd=store).stdout.splitlines()
    if sorted(staged) != sorted(rels):
        _run(("git", "reset", "--quiet"), cwd=store, check=False)
        raise ContinuityError("continuity index contained unexpected staged paths")
    _run(("git", "commit", "-q", "-m", message, "--", *rels), cwd=store)
    return _git(store, "rev-parse", "HEAD")


def _current_branch(store: Path) -> str:
    return _git(store, "branch", "--show-current") or "main"


def _sync_locked(source_root: Path, store: Path) -> dict[str, Any]:
    remote = _configured_remote(source_root)
    if not remote:
        return {"remote_synced": False, "sync_reason": "remote_unconfigured"}
    _ensure_origin(store, remote)
    branch = _current_branch(store)
    fetch = _run(("git", "fetch", "--quiet", "origin"), cwd=store, check=False)
    if fetch.returncode != 0:
        return {"remote_synced": False, "sync_reason": "fetch_failed"}

    remote_ref = f"refs/remotes/origin/{branch}"
    has_remote_branch = _run(("git", "show-ref", "--verify", "--quiet", remote_ref), cwd=store, check=False)
    if has_remote_branch.returncode == 0:
        rebase = _run(("git", "rebase", f"origin/{branch}"), cwd=store, check=False)
        if rebase.returncode != 0:
            _run(("git", "rebase", "--abort"), cwd=store, check=False)
            return {"remote_synced": False, "sync_reason": "rebase_conflict"}

    for attempt in range(2):
        push = _run(("git", "push", "--quiet", "origin", f"HEAD:{branch}"), cwd=store, check=False)
        if push.returncode == 0:
            return {"remote_synced": True, "sync_reason": "ok"}
        if attempt == 0:
            fetch = _run(("git", "fetch", "--quiet", "origin"), cwd=store, check=False)
            if fetch.returncode != 0:
                break
            has_remote_branch = _run(
                ("git", "show-ref", "--verify", "--quiet", remote_ref), cwd=store, check=False
            )
            if has_remote_branch.returncode == 0:
                rebase = _run(("git", "rebase", f"origin/{branch}"), cwd=store, check=False)
                if rebase.returncode != 0:
                    _run(("git", "rebase", "--abort"), cwd=store, check=False)
                    return {"remote_synced": False, "sync_reason": "rebase_conflict"}
    return {"remote_synced": False, "sync_reason": "push_failed"}


def sync_store(source_root: Path) -> dict[str, Any]:
    store = ensure_store(source_root)
    with store_lock(store):
        return _sync_locked(source_root, store)


def create_handoff(source_root: Path, input_path: Path) -> dict[str, Any]:
    data = _read_handoff_input(input_path)
    store = ensure_store(source_root)
    handoff_id = _handoff_id()
    manifest, markdown = _manifest_and_markdown(source_root, data, handoff_id)
    project = manifest["project_id"]
    handoff_dir = store / "projects" / project / "handoffs" / handoff_id
    manifest_path = handoff_dir / "manifest.json"
    markdown_path = handoff_dir / "HANDOFF.md"

    with store_lock(store):
        handoff_dir.mkdir(parents=True, exist_ok=False)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(markdown, encoding="utf-8")
        commit = _commit_paths(
            store,
            (manifest_path, markdown_path),
            f"handoff: {project}/{manifest['workstream_id']} {handoff_id}",
        )
        sync_result = _sync_locked(source_root, store)
    return {
        "handoff_id": handoff_id,
        "source_portability": manifest["source_portability"],
        "continuity_commit": commit,
        **sync_result,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityError(f"invalid continuity JSON at {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityError(f"invalid continuity JSON object at {path.name}")
    return value


def _head_relation(source_root: Path, handoff_head: str) -> str:
    current = _git(source_root, "rev-parse", "HEAD")
    if handoff_head == current:
        return "EXACT_HEAD"
    exists = _run(("git", "cat-file", "-e", f"{handoff_head}^{{commit}}"), cwd=source_root, check=False)
    if exists.returncode != 0:
        return "UNKNOWN"
    if _run(("git", "merge-base", "--is-ancestor", handoff_head, current), cwd=source_root, check=False).returncode == 0:
        return "CURRENT_IS_DESCENDANT"
    if _run(("git", "merge-base", "--is-ancestor", current, handoff_head), cwd=source_root, check=False).returncode == 0:
        return "HANDOFF_IS_DESCENDANT"
    return "DIVERGED"


def _closure_ids(store: Path, project: str) -> set[str]:
    root = store / "projects" / project / "closures"
    if not root.exists():
        return set()
    return {path.stem for path in root.glob("*.json") if path.is_file()}


def list_candidates(
    source_root: Path,
    *,
    workstream: str = "",
    goal_id: str = "",
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    store = ensure_store(source_root)
    project = _project_id(source_root)
    handoff_root = store / "projects" / project / "handoffs"
    if not handoff_root.exists():
        return []
    closed = _closure_ids(store, project)
    rows: list[dict[str, Any]] = []
    for manifest_path in handoff_root.glob("*/manifest.json"):
        manifest = _load_json(manifest_path)
        hid = str(manifest.get("handoff_id", ""))
        is_closed = hid in closed
        if is_closed and not include_closed:
            continue
        if workstream and manifest.get("workstream_id") != workstream:
            continue
        if goal_id and manifest.get("goal_id") != goal_id:
            continue
        rows.append(
            {
                "handoff_id": hid,
                "workstream_id": manifest.get("workstream_id", ""),
                "goal_id": manifest.get("goal_id", ""),
                "created_at": manifest.get("created_at", ""),
                "source_head": manifest.get("source_head", ""),
                "source_portability": manifest.get("source_portability", "metadata_only"),
                "head_relation": _head_relation(source_root, str(manifest.get("source_head", ""))),
                "closed": is_closed,
            }
        )
    return sorted(rows, key=lambda row: (row["created_at"], row["handoff_id"]), reverse=True)


def show_handoff(source_root: Path, handoff_id: str) -> str:
    hid = _safe_id(handoff_id, field="handoff_id")
    store = ensure_store(source_root)
    path = store / "projects" / _project_id(source_root) / "handoffs" / hid / "HANDOFF.md"
    if not path.is_file():
        raise ContinuityError("handoff not found")
    return path.read_text(encoding="utf-8")


def close_handoff(source_root: Path, handoff_id: str, reason_file: Path | None) -> dict[str, Any]:
    hid = _safe_id(handoff_id, field="handoff_id")
    store = ensure_store(source_root)
    project = _project_id(source_root)
    handoff = store / "projects" / project / "handoffs" / hid / "manifest.json"
    if not handoff.is_file():
        raise ContinuityError("handoff not found")
    reason = "closed"
    if reason_file is not None:
        try:
            raw = reason_file.read_bytes()
        except OSError as exc:
            raise ContinuityError("unable to read private closure reason file") from exc
        if len(raw) > 4096:
            raise ContinuityError("closure reason exceeds 4096 bytes")
        reason = raw.decode("utf-8").strip() or "closed"
        findings = _secret_findings(reason)
        if findings:
            raise ContinuityError("closure reason rejected by secret scan: " + ", ".join(findings))
    closure_path = store / "projects" / project / "closures" / f"{hid}.json"
    payload = {"schema": _SCHEMA, "handoff_id": hid, "closed_at": _now(), "reason": reason}
    with store_lock(store):
        if closure_path.exists():
            raise ContinuityError("handoff already closed")
        closure_path.parent.mkdir(parents=True, exist_ok=True)
        closure_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        commit = _commit_paths(store, (closure_path,), f"close: {project}/{hid}")
        sync_result = _sync_locked(source_root, store)
    return {"handoff_id": hid, "continuity_commit": commit, **sync_result}


def configure(
    source_root: Path,
    *,
    remote: str | None,
    path: str | None,
    project: str | None,
) -> dict[str, Any]:
    if remote is not None:
        _validate_remote(remote)
        _config_set(source_root, f"{_CONFIG_PREFIX}.remote", remote)
    if project is not None:
        _config_set(source_root, f"{_CONFIG_PREFIX}.project", _safe_id(project, field="project"))
    if path is not None:
        candidate = Path(path).expanduser().resolve()
        _validate_store_outside_source(source_root, candidate)
        _config_set(source_root, f"{_CONFIG_PREFIX}.path", str(candidate))
    elif not _config_get(source_root, f"{_CONFIG_PREFIX}.path"):
        _config_set(source_root, f"{_CONFIG_PREFIX}.path", str(_default_store_path(source_root)))
    store = ensure_store(source_root)
    return {
        "configured": True,
        "project_id": _project_id(source_root),
        "remote_configured": bool(_configured_remote(source_root)),
        "store_exists": (store / ".git").exists(),
    }


def status(source_root: Path) -> dict[str, Any]:
    store = _store_path(source_root)
    _validate_store_outside_source(source_root, store)
    remote = _configured_remote(source_root)
    store_exists = (store / ".git").exists()
    pending = None
    if store_exists:
        pending_raw = _git(store, "rev-list", "--count", "@{upstream}..HEAD", check=False)
        pending = int(pending_raw) if pending_raw.isdigit() else None
    return {
        "project_id": _project_id(source_root),
        "remote_configured": bool(remote),
        "store_exists": store_exists,
        "pending_commits": pending,
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_config = sub.add_parser("configure", help="configure private continuity locally")
    p_config.add_argument("--remote")
    p_config.add_argument("--path")
    p_config.add_argument("--project")

    sub.add_parser("status", help="show redacted local continuity status")

    p_handoff = sub.add_parser("handoff", help="create and locally commit a private handoff")
    p_handoff.add_argument("--input", required=True, type=Path)

    p_candidates = sub.add_parser("candidates", help="list explicit historical candidates")
    p_candidates.add_argument("--workstream", default="")
    p_candidates.add_argument("--goal-id", default="")
    p_candidates.add_argument("--include-closed", action="store_true")

    p_show = sub.add_parser("show", help="show one explicitly selected handoff")
    p_show.add_argument("handoff_id")

    p_close = sub.add_parser("close", help="append a closure record")
    p_close.add_argument("handoff_id")
    p_close.add_argument("--reason-file", type=Path)

    sub.add_parser("sync", help="sync the private continuity Git store")
    return parser


def _redacted_error(exc: BaseException, source_root: Path | None = None) -> str:
    text = str(exc) or exc.__class__.__name__
    if source_root is not None:
        replacements = [str(source_root)]
        try:
            replacements.append(str(_store_path(source_root)))
            remote = _config_get(source_root, f"{_CONFIG_PREFIX}.remote")
            if remote:
                replacements.append(remote)
        except Exception:
            pass
        for value in replacements:
            if value:
                text = text.replace(value, "<private>")
    return text


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root: Path | None = None
    try:
        source_root = source_root_from_cwd()
        if args.command == "configure":
            _print_json(configure(source_root, remote=args.remote, path=args.path, project=args.project))
        elif args.command == "status":
            _print_json(status(source_root))
        elif args.command == "handoff":
            _print_json(create_handoff(source_root, args.input.resolve()))
        elif args.command == "candidates":
            _print_json(
                list_candidates(
                    source_root,
                    workstream=args.workstream,
                    goal_id=args.goal_id,
                    include_closed=args.include_closed,
                )
            )
        elif args.command == "show":
            print(show_handoff(source_root, args.handoff_id), end="")
        elif args.command == "close":
            _print_json(
                close_handoff(
                    source_root,
                    args.handoff_id,
                    args.reason_file.resolve() if args.reason_file else None,
                )
            )
        elif args.command == "sync":
            _print_json(sync_store(source_root))
        else:  # pragma: no cover
            raise ContinuityError("unknown command")
        return 0
    except (ContinuityError, OSError, subprocess.SubprocessError) as exc:
        print(f"continuity: {_redacted_error(exc, source_root)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
