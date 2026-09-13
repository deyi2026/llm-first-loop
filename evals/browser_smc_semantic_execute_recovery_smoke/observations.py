"""Harness observations persisted independently of worker completion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from evals.browser_smc_semantic_execute_recovery_smoke.audit_observations import audit_data


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def run_profile(name: str) -> dict[str, Any]:
    if name not in {"repeat12", "diagnostic16"}:
        raise ValueError("unknown experiment profile")
    return {
        "name": name,
        "max_iterations": 12 if name == "repeat12" else 16,
        "qualification_eligible": name == "repeat12",
        "worker_timeout_s": 240,
    }


def finalize_worker(run_dir: Path, *, timed_out: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    errors = []
    for filename in ("worker-startup.json", "worker-result.json"):
        path = run_dir / filename
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("not an object")
                payload.update(value)
            except ValueError:
                errors.append(filename)
    payload["surface_status"] = (
        "observed" if isinstance(payload.get("surface"), dict) else "unknown"
    )
    payload.setdefault("surface", None)
    payload["timed_out"] = timed_out
    payload["observation_read_errors"] = errors
    if timed_out:
        payload["status"] = "TIMEOUT"
    facts = audit_data(run_dir / ".lfldata")
    payload["durable_observation"] = facts
    for key in (
        "partial_checkpoint_count",
        "partial_only_loop_rounds",
        "decided_but_not_dispatched_rounds",
    ):
        if timed_out or key not in payload:
            payload[key] = facts.get(key)
    if facts.get("coverage") == "available_prefix":
        payload.setdefault(
            "receipt_facts",
            {
                "navigate_ok_count": facts["navigate_ok_count"],
                "object_ok_count": facts["object_ok_count"],
                "terminal_count": facts["terminal_action_count"],
            },
        )
    atomic_json(run_dir / "worker-observation.json", payload)
    return payload


def declared_round(run_dir: Path) -> int | None:
    """Round of latest declared tool dispatch, recorded before fixture mutation."""
    logs = list((run_dir / ".lfldata/event_logs").glob("*.jsonl"))
    if len(logs) != 1:
        return None
    rounds = []
    for line in logs[0].read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        payload = event.get("payload") or {}
        if event.get("type") == "tool.execution.started" and isinstance(payload.get("round"), int):
            rounds.append(payload["round"])
    return max(rounds) if rounds else None
