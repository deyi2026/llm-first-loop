"""Read-only Method census and declaration evidence; never lifecycle verdicts."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from llm_loop.methods.store import MethodStore
from llm_loop.timekeeping import system_local_now_iso


def _inventory(directory: Path) -> dict[str, Any]:
    store = MethodStore(directory)
    statuses: Counter[str] = Counter()
    legacy: Counter[str] = Counter()
    cards: list[dict[str, Any]] = []
    unreadable: list[str] = []
    invalid: list[str] = []
    body_status_lines = 0
    paths = sorted(directory.glob("*/METHOD.md"))
    for path in paths:
        relative = path.relative_to(directory).as_posix()
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError):
            unreadable.append(relative)
            continue
        legacy.update(re.findall(r"^status:\s*([a-z]+)\s*$", text, re.MULTILINE))
        try:
            record = store.get(f"method:{path.parent.name}")
        except (OSError, UnicodeError, ValueError):
            record = None
        if record is None:
            invalid.append(relative)
            continue
        statuses[record.status] += 1
        body_status_lines += len(re.findall(r"^status:\s*([a-z]+)\s*$", record.body, re.MULTILINE))
        cards.append({
            "ref": record.method_ref, "path": relative, "status": record.status,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return {
        "exists": directory.is_dir(), "files": len(paths), "valid_cards": len(cards),
        "statuses": dict(sorted(statuses.items())), "cards": cards,
        "unreadable": unreadable, "invalid": invalid,
        "legacy_whole_file_status_lines": dict(sorted(legacy.items())),
        "body_status_lines_excluded": body_status_lines,
    }


def _read_jsonl(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "missing", "rows": [], "invalid_lines": [], "sha256": None}
    try:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return {"state": "unreadable", "rows": [], "invalid_lines": [], "error": type(exc).__name__}
    rows: list[dict[str, Any]] = []
    invalid: list[int] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            invalid.append(number)
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            invalid.append(number)
    return {"state": "partial" if invalid else "readable", "rows": rows,
            "invalid_lines": invalid, "sha256": hashlib.sha256(raw).hexdigest()}


def build_report(methods_dir: Path, seed_dir: Path | None = None) -> dict[str, Any]:
    started = system_local_now_iso()
    runtime = _inventory(methods_dir)
    seeds = _inventory(seed_dir) if seed_dir is not None else None
    usage = _read_jsonl(methods_dir / "usage.jsonl")
    rows = usage.pop("rows")
    decisions = Counter(str(row.get("decision", "unknown")) for row in rows)
    refs = {str(row["method_ref"]) for row in rows if row.get("method_ref")}
    qualification_states: Counter[str] = Counter()
    benefit_claims: Counter[str] = Counter()
    qualification_rows = 0
    for path in sorted(methods_dir.glob("*/qualification.jsonl")):
        ledger = _read_jsonl(path)
        qualification_states[ledger["state"]] += 1
        for row in ledger["rows"]:
            qualification_rows += 1
            benefit_claims[str(row.get("task_benefit", "unknown"))] += 1
    runtime_refs = {card["ref"] for card in runtime["cards"]}
    return {
        "schema": "lfl.method_evidence.v1",
        "sample_started_at": started, "sample_finished_at": system_local_now_iso(),
        "snapshot_atomic": False,
        "census_rule": "MethodStore first frontmatter; runtime and seed reported separately",
        "runtime": runtime, "seed": seeds,
        "declarations": {
            **usage, "valid_rows": len(rows), "distinct_methods": len(refs),
            "decisions": dict(sorted(decisions.items())),
            "declared_applied_or_adapted": decisions["applied"] + decisions["adapted"],
            "missing_episode_or_hash": sum(not row.get("episode_ref") or not row.get("method_content_hash") for row in rows),
            "refs_outside_runtime_pool": sorted(refs - runtime_refs),
        },
        "qualification": {
            "files_by_read_state": dict(sorted(qualification_states.items())),
            "valid_rows": qualification_rows, "task_benefit_claims": dict(sorted(benefit_claims.items())),
            "independent_verification": "not_evaluated",
        },
        "funnel": {
            "seen": {"state": "not_measured", "count": None},
            "decision": {"state": usage["state"], "count": len(rows) if usage["state"] in {"readable", "partial"} else None},
            "executed": {"state": "not_measured", "count": None},
            "benefit": {"state": "not_independently_verified", "count": None},
        },
        "limitations": [
            "Historical event telemetry is incomplete; no conversion rate denominator.",
            "Legacy application_proven in usage.jsonl is a model declaration, not execution evidence.",
            "Qualification task_benefit fields are claims until independent task evidence is checked.",
            "Missing/unreadable ledger is unknown, not proof of zero use.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--methods-dir", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.methods_dir, args.seed_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    runtime = report["runtime"]
    return int(not runtime["exists"] or bool(runtime["unreadable"] or runtime["invalid"]))


if __name__ == "__main__":
    raise SystemExit(main())
