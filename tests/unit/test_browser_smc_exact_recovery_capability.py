"""FC2-A: exact Evidence recovery must be reachable without semantic automation."""

from evals.browser_smc_semantic_execute_recovery_smoke import protocol


def test_semantic_execute_surface_exposes_only_exact_recovery_capability():
    allowed = tuple(protocol.ARMS["semantic_execute"]["allowed_tools"])

    assert "read_evidence" in allowed
    assert allowed.count("read_evidence") == 1
    assert "search_evidence" not in allowed
    assert "list_evidence" not in allowed
    assert "search_records" not in allowed


def test_recovery_capability_does_not_change_model_owned_operation_surface():
    arm = protocol.ARMS["semantic_execute"]

    assert arm["mutation_tool"] == "browser_semantic_execute"
    assert set(arm["allowed_tools"]) == {
        "browser_perceive",
        "browser_wait_scope_url",
        "browser_wait_scope_ready",
        "browser_wait_scope_count",
        "browser_wait_object_state",
        "browser_wait_object_text",
        "get_tool_schema",
        "read_evidence",
        "browser_semantic_execute",
    }


def test_fc2_runner_freezes_evidence_enforce_for_recovery_refs(tmp_path):
    from evals.browser_smc_semantic_execute_recovery_smoke import run_a2

    env = run_a2._base_env(tmp_path)
    assert env["EVIDENCE_MODE"] == "enforce"
