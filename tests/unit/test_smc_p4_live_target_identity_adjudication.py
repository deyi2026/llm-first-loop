"""Qualification regression for the first real P4-LIVE target-identity failure."""
from evals.smc_semantic_logic_p4_live.target_identity_adjudication import adjudicate


def test_live_capture_and_actuator_target_identity_representations_are_incompatible() -> None:
    result = adjudicate()
    assert result["binding_uses_prefixed_page_token"] is True
    assert result["binding_hash_matches_prefixed_capture_identity"] is True
    assert result["binding_hash_matches_actuator_raw_identity"] is False
    assert result["identity_contract_compatible"] is False
    assert result["expected_live_failure_code"] == "browser_target_precondition_mismatch"
    assert result["model_requests"] == 0
    assert result["browser_mutations"] == 0
