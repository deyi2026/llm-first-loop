#!/usr/bin/env python3
"""Deterministic qualification-only reproducer for the P4-LIVE R12 live failure.

This file does not execute a Browser mutation. It freezes the representation
boundary exposed by the first real L02 canary: perception canonicalizes a raw
CDP target id with a target: prefix while the real mutation actuator validates
the SHA-256 of the raw target id returned by /json/list.
"""
from __future__ import annotations

import hashlib
import json

RAW_TARGET_ID = "P4LIVE-DETERMINISTIC-TARGET"
CAPTURE_PAGE_TOKEN = f"target:{RAW_TARGET_ID}"

def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def adjudicate() -> dict[str, object]:
    binding_hash = _sha(CAPTURE_PAGE_TOKEN)
    actuator_hash = _sha(RAW_TARGET_ID)
    return {
        "schema": "smc.semantic_logic_p4_live_target_identity_adjudication.v0.1",
        "raw_target_id": RAW_TARGET_ID,
        "capture_page_token": CAPTURE_PAGE_TOKEN,
        "binding_browser_target_id_sha256": binding_hash,
        "actuator_expected_target_id_sha256": actuator_hash,
        "binding_uses_prefixed_page_token": f"target:{RAW_TARGET_ID}" == CAPTURE_PAGE_TOKEN,
        "binding_hash_matches_prefixed_capture_identity": binding_hash == _sha(CAPTURE_PAGE_TOKEN),
        "binding_hash_matches_actuator_raw_identity": binding_hash == actuator_hash,
        "identity_contract_compatible": binding_hash == actuator_hash,
        "expected_live_failure_code": "browser_target_precondition_mismatch",
        "model_requests": 0,
        "browser_mutations": 0,
    }

def main() -> int:
    result = adjudicate()
    print(json.dumps(result, sort_keys=True, indent=2))
    reproduced = (
        result["binding_uses_prefixed_page_token"] is True
        and result["binding_hash_matches_prefixed_capture_identity"] is True
        and result["binding_hash_matches_actuator_raw_identity"] is False
        and result["identity_contract_compatible"] is False
    )
    return 0 if reproduced else 2

if __name__ == "__main__":
    raise SystemExit(main())
