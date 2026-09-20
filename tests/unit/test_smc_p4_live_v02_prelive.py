"""Deterministic PRE-LIVE contracts for P4-LIVE v0.2 requalification."""
from __future__ import annotations

import json
from pathlib import Path

from llm_loop.tools.p4_live_scope import P4_LIVE_CANARY_TOOL_SCOPE

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = json.loads((ROOT / "evals/smc_semantic_logic_p4_live/PROTOCOL.v0.2-ACTIONREF.json").read_text())
MANIFEST = json.loads((ROOT / "evals/smc_semantic_logic_p4_live/P4-LIVE-v0.2-EXECUTION-MANIFEST.json").read_text())


def test_v02_preserves_frozen_prior_negative_qualification() -> None:
    prior = PROTOCOL["frozen_prior_negative_qualification"]
    assert prior["git_sha"] == "9a11fe4c43cc83f53bf2baf62d0782c91e1d4242"
    assert prior["immutable"] is True
    assert prior["rerun_or_reclassify_old_l02"] is False
    assert MANIFEST["prior_v01_result_namespace_read_only"].endswith(
        "P4-LIVE-QUALIFICATION-v0.1-20260920"
    )


def test_v02_exact_tool_scope_and_zero_prelive_authority() -> None:
    assert set(PROTOCOL["exact_canary_tool_scope"]) == set(P4_LIVE_CANARY_TOOL_SCOPE)
    assert set(MANIFEST["tool_scope"]) == set(P4_LIVE_CANARY_TOOL_SCOPE)
    assert PROTOCOL["authorization"] == {
        "this_protocol_authorizes_live_model_requests": 0,
        "this_protocol_authorizes_browser_mutations": 0,
        "deploy_restart_merge_main": False,
    }
    assert MANIFEST["model_requests_authorized_before_human_checkpoint"] == 0
    assert MANIFEST["browser_mutations_authorized_before_human_checkpoint"] == 0


def test_v02_manifest_has_exact_new_namespace_and_frozen_row_order() -> None:
    rows = MANIFEST["row_order"]
    assert len(rows) == 20
    assert len(set(rows)) == 20
    assert rows[0] == "V02-L01_navigate_success"
    assert rows[-1] == "V02-L20_transport_ambiguity_no_replay"
    assert all(row.startswith("V02-L") for row in rows)
    assert MANIFEST["prelive_only"] is True
    assert MANIFEST["first_live_boundary"] == "BEFORE_V02-L01_navigate_success_MODEL_REQUEST"
    assert "P4-LIVE-v0.2-QUALIFICATION-20260920" in MANIFEST["result_namespace"]
    assert MANIFEST["retry_policy"] == "NO_RETRY_NO_SUBSTITUTION_NO_ROW_REORDER"


def test_v02_r12_identity_contract_is_raw_target_digest_only() -> None:
    r12 = PROTOCOL["r12_target_identity_contract"]
    assert r12["perception_private_page_token"] == "target:<raw_cdp_target_id>"
    assert r12["binding_identity_digest"] == "sha256(raw_cdp_target_id)"
    assert r12["actuator_identity_digest"] == "sha256(raw_cdp_target_id)"
    assert r12["target_search_guess_rebind_or_successor_substitution"] is False
    assert r12["empty_or_malformed_identity"] == "FAIL_CLOSED"
