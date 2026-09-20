#!/usr/bin/env python3
"""Deterministic validator/aggregator for frozen P4-LIVE v0.2 row artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ROW_ROOT = ROOT / "evals/smc_semantic_logic_p4_live/results/P4-LIVE-v0.2-QUALIFICATION-20260920"
MANIFEST_PATH = ROOT / "evals/smc_semantic_logic_p4_live/P4-LIVE-v0.2-EXECUTION-MANIFEST.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object JSON: {path}")
    return value


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def validate(output: Path) -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH)
    manifest_rows = list(manifest.get("row_order") or [])
    expected_ids = [f"V02-L{i:02d}" for i in range(1, 21)]
    _require(len(manifest_rows) == 20, "manifest row count is not 20")
    _require(
        [str(row).split("_", 1)[0] for row in manifest_rows] == expected_ids,
        "manifest row id order differs from V02-L01..V02-L20",
    )

    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for row_id in expected_ids:
        path = ROW_ROOT / f"{row_id}.json"
        _require(path.is_file(), f"missing row artifact: {row_id}")
        row = _load(path)
        _require(row.get("row") == row_id, f"row id mismatch: {row_id}")
        _require(row.get("status") == "PASS", f"row not PASS: {row_id}")
        rows.append(row)
        hashes[str(path.relative_to(ROOT))] = _sha(path)

    # Success rows: exactly one model request + one intended dispatch + durable success.
    for row in rows[:5]:
        rid = str(row["row"])
        _require(row.get("schema") == "smc.p4_live.v02.success_row.v0.2", f"schema {rid}")
        _require(row.get("model_requests") == 1, f"model request count {rid}")
        _require(row.get("browser_dispatches") == 1, f"dispatch count {rid}")
        _require(row.get("receipt_statuses") == ["running", "ok"], f"receipts {rid}")
        _require(row.get("physical_effect_ok") is True, f"physical effect {rid}")
        _require(row.get("outer_receipt_committed") is True, f"outer receipt {rid}")
        _require(row.get("automatic_retry_performed") is False, f"retry {rid}")
        actual = list(row.get("actual") or [])
        _require(len(actual) == 1, f"tool-call multiplicity {rid}")
        _require(
            {"name": actual[0].get("name"), "arguments": actual[0].get("arguments")}
            == row.get("expected"),
            f"declaration mismatch {rid}",
        )
        _require(bool(actual[0].get("id")), f"provider call id missing {rid}")
        _require(bool(row.get("execution_bridge_id")), f"bridge missing {rid}")
        _require(bool(row.get("grounding_ref")), f"grounding missing {rid}")
        _require(bool(row.get("inner_action_id")), f"inner action missing {rid}")
        _require(bool(row.get("browser_target_id_sha256")), f"target hash missing {rid}")

    # Rejection rows L06-L15: no model and no candidate physical dispatch/effect.
    for row in rows[5:15]:
        rid = str(row["row"])
        _require(row.get("schema") == "smc.p4_live.v02.rejection_row.v0.2", f"schema {rid}")
        _require(row.get("model_requests") == 0, f"model request count {rid}")
        _require(row.get("browser_dispatches") == 0, f"unexpected dispatch {rid}")
        _require(row.get("click_effects") == 0, f"unexpected click effect {rid}")
        _require(row.get("automatic_retry_performed") is False, f"retry {rid}")

    duplicate = rows[15]
    _require(duplicate.get("model_requests") == 0, "L16 model request")
    _require(duplicate.get("browser_dispatches") == 1, "L16 must have one total dispatch")
    _require(duplicate.get("click_effects") == 1, "L16 must have one total effect")
    dup_facts = duplicate.get("facts") or {}
    _require((dup_facts.get("first") or {}).get("status") == "success", "L16 first failed")
    _require((dup_facts.get("second") or {}).get("status") == "failure", "L16 second not rejected")
    _require(
        "duplicate_action_id" in str((dup_facts.get("second") or {}).get("content") or ""),
        "L16 duplicate reason",
    )

    l17, l18, l19, l20 = rows[16:20]
    for row in (l17, l18, l19, l20):
        _require(
            row.get("schema") == "smc.p4_live.v02.recovery_row.v0.2",
            f"recovery schema {row.get('row')}",
        )
        _require(row.get("model_requests") == 0, f"recovery model request {row.get('row')}")
        _require(row.get("automatic_replay_performed") is False, f"auto replay {row.get('row')}")

    _require(l17.get("browser_dispatches") == 0 and l17.get("click_effects") == 0, "L17 effect")
    _require(
        (l17.get("facts") or {}).get("recovery", {}).get("classification")
        == "prepared_before_browser_running",
        "L17 state",
    )
    _require(
        (l17.get("facts") or {})
        .get("recovery", {})
        .get("recovery_metadata", {})
        .get("auto_reexecuted")
        is False,
        "L17 replay",
    )

    _require(l18.get("browser_dispatches") == 0 and l18.get("click_effects") == 0, "L18 effect")
    _require(
        (l18.get("facts") or {}).get("receipt_statuses_before_recovery") == ["running"],
        "L18 running receipt",
    )
    _require(
        (l18.get("facts") or {}).get("recovery", {}).get("classification")
        == "browser_running_outcome_unknown",
        "L18 state",
    )
    _require(
        (l18.get("facts") or {})
        .get("recovery", {})
        .get("recovery_metadata", {})
        .get("auto_reexecuted")
        is False,
        "L18 replay",
    )

    _require(l19.get("browser_dispatches") == 1 and l19.get("click_effects") == 1, "L19 effect")
    _require(
        (l19.get("facts") or {}).get("receipt_statuses_before_recovery") == ["running", "ok"],
        "L19 receipts",
    )
    _require(
        (l19.get("facts") or {}).get("recovery", {}).get("classification")
        == "browser_terminal_exact",
        "L19 state",
    )
    _require(
        (l19.get("facts") or {})
        .get("recovery", {})
        .get("recovery_metadata", {})
        .get("auto_reexecuted")
        is False,
        "L19 replay",
    )

    _require(
        l20.get("browser_dispatches") == 1 and l20.get("click_effects") == 1, "L20 possible effect"
    )
    l20_facts = l20.get("facts") or {}
    _require(l20_facts.get("receipt_statuses") == ["running", "failed"], "L20 receipts")
    _require(
        "dispatch_outcome_ambiguous"
        in list((l20_facts.get("terminal_completeness") or {}).get("reasons") or []),
        "L20 ambiguity",
    )
    _require(
        (l20_facts.get("terminal_retry") or {}).get("automatic_retry_performed") is False,
        "L20 retry",
    )
    _require(l20_facts.get("recovered_again") == 0, "L20 replay via recovery")

    total_model_requests = sum(int(row.get("model_requests") or 0) for row in rows)
    total_candidate_dispatches = sum(int(row.get("browser_dispatches") or 0) for row in rows)
    _require(total_model_requests == 5, "total model requests must be exactly 5")
    _require(total_candidate_dispatches == 8, "total candidate dispatch accounting mismatch")

    result = {
        "schema": "smc.semantic_logic_p4_live_v02_result.v0.2",
        "status": "QUALIFIED",
        "qualification_id": manifest.get("qualification_id"),
        "base_prelive_result_sha": "5849992e7dc39dad0409337e54b29956b61aba78",
        "row_count": 20,
        "all_rows_pass": True,
        "row_order": expected_ids,
        "model_requests": total_model_requests,
        "success_rows": 5,
        "zero_dispatch_rejection_rows": 10,
        "duplicate_row_total_dispatches": int(duplicate.get("browser_dispatches") or 0),
        "recovery_rows": 4,
        "total_candidate_dispatches": total_candidate_dispatches,
        "automatic_row_retries": 0,
        "automatic_replays": 0,
        "row_artifact_sha256": hashes,
        "manifest_sha256": _sha(MANIFEST_PATH),
        "legacy_v01_result_immutable": True,
        "production_patch_during_live": False,
        "deployment_restart_merge": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
