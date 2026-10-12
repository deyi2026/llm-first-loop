"""Program-owned mechanical continuity facts for pressure-ended long runs.

This module deliberately does not summarize task semantics or hidden reasoning.  It
only carries facts LFL already owns durably: exact read identities/versions,
Evidence refs, and Goal/Task frontier identities.  The provider-visible projection is
explicitly historical/non-authoritative/non-instructional.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from llm_loop.core.run_context import workspace_base

MANIFEST_VERSION = 1
MAX_READ_ANCHORS = 48
MAX_WIRE_CHARS = 12_000


def canonical_read_key(name: str, arguments: dict[str, Any]) -> str:
    """Stable exact read identity; call_id is intentionally excluded."""

    raw = json.dumps(
        {"name": str(name), "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


def _goal_frontier_snapshot(data_dir: str | Path, session_id: str) -> dict[str, Any]:
    """Return bounded mechanical Goal/Task state; failure is an empty fact set."""

    try:
        from llm_loop.introspection.goal import GoalStore
        from llm_loop.introspection.task_store import TaskStore

        audit_dir = Path(data_dir) / "audit"
        goal = GoalStore(audit_dir).get(prefer_session_id=session_id, strict_session=True)
        if not isinstance(goal, dict):
            return {}
        goal_id = str(goal.get("id") or "")
        out: dict[str, Any] = {
            "goal_id": goal_id,
            "goal_generation": GoalStore.generation_of(goal),
            "goal_status": str(goal.get("status") or ""),
        }
        checkpoints = goal.get("checkpoints")
        if isinstance(checkpoints, list) and checkpoints:
            cp = checkpoints[-1]
            if isinstance(cp, dict):
                out["latest_checkpoint"] = {
                    key: str(cp.get(key) or "")[:1200]
                    for key in ("what", "evidence", "path", "next")
                    if cp.get(key)
                }
        if goal_id:
            frontier = TaskStore(audit_dir).compute_frontier(goal_id)
            if isinstance(frontier, dict):
                def _task_id(item: Any) -> str:
                    if isinstance(item, dict) and "task" in item:
                        item = item.get("task")
                    if isinstance(item, dict):
                        return str(item.get("task_id") or item.get("id") or "")
                    return str(getattr(item, "task_id", "") or getattr(item, "id", ""))

                out["task_frontier"] = {
                    "total": int(frontier.get("total", 0) or 0),
                    "open_count": int(frontier.get("open_count", 0) or 0),
                    "ready_ids": [
                        _task_id(item)
                        for item in (frontier.get("ready") or [])[:12]
                        if _task_id(item)
                    ],
                    "in_progress_ids": [
                        _task_id(item)
                        for item in (frontier.get("in_progress") or [])[:12]
                        if _task_id(item)
                    ],
                }
        return out
    except Exception:
        return {}


def build_longrun_manifest(
    *,
    session_id: str,
    data_dir: str | Path,
    read_cache: dict[str, dict[str, Any]] | None,
    pressure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build bounded durable handoff facts from already-observed runtime state."""

    rows = []
    for key, raw in list((read_cache or {}).items())[-MAX_READ_ANCHORS:]:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "key": str(key),
                "tool": str(raw.get("tool") or ""),
                "arguments": dict(raw.get("arguments") or {}),
                "evidence_ref": str(raw.get("evidence_ref") or ""),
                "source_version_token": str(raw.get("source_version_token") or ""),
                "artifact_ref": str(raw.get("artifact_ref") or ""),
            }
        )
    return {
        "version": MANIFEST_VERSION,
        "kind": "longrun_continuity",
        "reason": "ingress_pressure_or_overflow",
        "read_anchors": rows,
        "frontier": _goal_frontier_snapshot(data_dir, session_id),
        "pressure": dict(pressure or {}),
    }


def restore_read_cache(manifest: Any) -> dict[str, dict[str, Any]]:
    """Restore only structurally valid read anchors from one durable manifest."""

    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in manifest.get("read_anchors") or []:
        if not isinstance(row, dict):
            continue
        tool = str(row.get("tool") or "")
        args = row.get("arguments")
        key = str(row.get("key") or "")
        if tool not in {"read_file", "read_evidence"} or not isinstance(args, dict) or not key:
            continue
        if canonical_read_key(tool, args) != key:
            continue
        out[key] = dict(row)
    return out


def previous_overflow_manifest(messages: list[Any]) -> dict[str, Any] | None:
    """Return only the immediately-adjacent program overflow handoff."""

    for message in reversed(messages):
        role = str(getattr(message, "role", "") or "")
        if role == "user":
            return None
        if role != "assistant":
            continue
        md = getattr(message, "metadata", None)
        if not isinstance(md, dict):
            return None
        if not (
            md.get("program_final_placeholder") is True
            and str(md.get("run_end_reason") or "") in {"overflow", "projection_cannot_fit"}
        ):
            return None
        manifest = md.get("longrun_continuity_manifest")
        return dict(manifest) if isinstance(manifest, dict) else None
    return None


def continuity_wire(manifest: Any) -> dict[str, Any] | None:
    """Bounded provider-visible historical fact carrier; never an instruction."""

    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        return None
    payload = {
        "kind": "longrun_continuity",
        "historical": True,
        "authority": False,
        "instruction": False,
        "reason": str(manifest.get("reason") or ""),
        "frontier": manifest.get("frontier") if isinstance(manifest.get("frontier"), dict) else {},
        "read_anchors": manifest.get("read_anchors") if isinstance(manifest.get("read_anchors"), list) else [],
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > MAX_WIRE_CHARS:
        payload["read_anchors"] = list(payload["read_anchors"])[-16:]
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return {
        "role": "assistant",
        "content": "[longrun_continuity—not_instruction] " + text[:MAX_WIRE_CHARS],
    }


def file_version_still_matches(arguments: dict[str, Any], version_token: str) -> bool:
    """Cheap freshness proof for a prior read_file stat token.

    Immutable artifact refs are intrinsically stable. Filesystem paths require the
    exact mtime_ns+size token emitted by ReadFileTool; unknown token shapes fail open.
    """

    path = str(arguments.get("path") or "").strip()
    if path.startswith("artifact://v1/"):
        return bool(version_token.startswith("artifact-sha256:"))
    if not version_token.startswith("stat:") or not path:
        return False
    parts = version_token.split(":", 2)
    if len(parts) != 3:
        return False
    try:

        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(workspace_base()) / p
        st = p.stat()
        return f"stat:{st.st_mtime_ns}:{st.st_size}" == version_token
    except OSError:
        return False
