#!/usr/bin/env python3
"""Targeted delayed_wait arm wrapper; B changes compact descriptions only."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _consume_arg(name: str) -> str:
    try:
        index = sys.argv.index(name)
    except ValueError as exc:
        raise SystemExit(f"missing required {name}") from exc
    if index + 1 >= len(sys.argv):
        raise SystemExit(f"missing value for {name}")
    value = sys.argv[index + 1]
    del sys.argv[index : index + 2]
    return value


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    arm = _consume_arg("--arm")
    if arm not in {"A", "B"}:
        raise SystemExit(f"unknown arm: {arm}")
    try:
        result_index = sys.argv.index("--result-json")
        result_path = Path(sys.argv[result_index + 1])
    except (ValueError, IndexError) as exc:
        raise SystemExit("missing --result-json") from exc

    from evals.browser_smc_peer_capability_routing_red_mf534r1.scorer import (
        compact_description_treatment,
    )
    from llm_loop.tools import registry as registry_module

    compact = registry_module._COMPACT_TOOL_DESCRIPTIONS
    original_perceive = str(compact["browser_perceive"])
    original_operate = str(compact["browser_operate"])
    if arm == "B":
        treated_perceive, treated_operate = compact_description_treatment(
            original_perceive, original_operate
        )
        compact["browser_perceive"] = treated_perceive
        compact["browser_operate"] = treated_operate

    effective_perceive = str(compact["browser_perceive"])
    effective_operate = str(compact["browser_operate"])

    from evals.browser_smc_cognition_preserving_actuation_mf534 import worker as base_worker

    rc = int(base_worker.main())
    if result_path.is_file():
        doc = json.loads(result_path.read_text(encoding="utf-8"))
        doc["routing_ab_arm"] = arm
        doc["compact_treatment_applied"] = arm == "B"
        doc["compact_description_fingerprints"] = {
            "browser_perceive_sha256": _sha(effective_perceive),
            "browser_operate_sha256": _sha(effective_operate),
            "browser_perceive_chars": len(effective_perceive),
            "browser_operate_chars": len(effective_operate),
        }
        tmp = result_path.with_suffix(result_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(result_path)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
