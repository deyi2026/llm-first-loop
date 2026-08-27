from __future__ import annotations

import json
from pathlib import Path

from scripts.evidence.r2.fixtures import FIXTURES
from scripts.evidence.r2.runner import execute_run

ROOT = Path(__file__).resolve().parents[2]


def _row(seed_id: str, condition: str) -> dict[str, object]:
    return {
        "run_id": f"TEST-{seed_id}-{condition}",
        "provider": "minimax",
        "seed_id": seed_id,
        "condition": condition,
        "rep": 1,
    }


def test_r2_matrix_is_frozen_72_balanced_runs() -> None:
    matrix = json.loads((ROOT / "tests/fixtures/evidence_r2/matrix_v1.json").read_text())
    runs = matrix["runs"]
    assert matrix["random_seed"] == 20260826
    assert len(runs) == 72
    assert len({r["run_id"] for r in runs}) == 72
    for provider in ("minimax", "deepseek"):
        for seed_id in FIXTURES:
            for condition in ("B0", "E1"):
                assert (
                    sum(
                        r["provider"] == provider
                        and r["seed_id"] == seed_id
                        and r["condition"] == condition
                        for r in runs
                    )
                    == 3
                )


def test_r2_e1_reusable_dry_uses_hydration_without_source_repeat() -> None:
    for seed_id in ("F1", "F2", "F3", "F4", "F5"):
        result = execute_run(_row(seed_id, "E1"), dry=True)
        assert result["status"] == "COMPLETED"
        assert result["e1_success"] is True
        assert result["final_answer_exact"] is True
        assert result["source_execution_count"] == 1
        assert result["evidence_hydration_count"] == 4
        assert result["side_effect_duplicate_count"] == 0


def test_r2_f6_dry_refreshes_once_then_hydrates_new_evidence() -> None:
    result = execute_run(_row("F6", "E1"), dry=True)
    assert result["status"] == "COMPLETED"
    assert result["e1_success"] is True
    assert result["answer"] == "NEW-947"
    assert result["source_execution_count"] == 2
    assert result["evidence_hydration_count"] == 4
    assert result["stale_used_as_current"] is False
    assert result["freshness_probe_count"] == 1
    versions = [x["version"] for x in result["trace"] if x["kind"] == "source"]
    assert versions == ["f6-v1", "f6-v2"]


def test_r2_b0_is_observational_and_dry_demonstrates_repeat() -> None:
    reusable = execute_run(_row("F1", "B0"), dry=True)
    assert reusable["status"] == "COMPLETED"
    assert reusable["harness_success"] is True
    assert reusable["e1_success"] is None
    assert reusable["source_execution_count"] == 2
    assert reusable["evidence_hydration_count"] == 0

    side_effect = execute_run(_row("F4", "B0"), dry=True)
    assert side_effect["side_effect_duplicate_count"] == 1
    assert side_effect["e1_success"] is None


def test_r2_prompts_have_no_duplicate_suppression_instruction() -> None:
    bad = ("do not repeat", "never reread", "must use read_evidence", "不要重复", "禁止重读")
    texts = [
        (ROOT / "docs/RECOVERABILITY-R2-PRE-REGISTRATION-v1.md").read_text(),
        (ROOT / "scripts/evidence/r2/fixtures.py").read_text(),
        (ROOT / "scripts/evidence/r2/runner.py").read_text(),
    ]
    # The pre-registration may name forbidden phrases in its audit rule; model-visible fixture/runner strings may not.
    model_visible = "\n".join(texts[1:]).lower()
    for phrase in bad:
        assert phrase.lower() not in model_visible


def test_r2_frozen_scorer_passes_dry_contract_shape() -> None:
    from scripts.evidence.r2.score import score_runs

    payload = json.loads((ROOT / "data/audit/evidence_r2/runs_dry_v1.json").read_text())
    report = score_runs(payload)
    assert report["status"] == "PASS"
    assert report["safety"] == {"side_effect_duplicates": 0, "stale_as_current": 0}
    assert report["metrics"]["e1_reexecution_rate_reusable"]["rate"] == 0.0
    assert report["metrics"]["b0_reexecution_rate_reusable"]["rate"] == 1.0
    assert report["metrics"]["paired_reexecution_rate_delta_b0_minus_e1"]["delta"] == 1.0


def test_r2_invalid_evidence_ref_is_tool_failure_not_infra(monkeypatch) -> None:
    import scripts.evidence.r2.runner as runner
    from llm_loop.core.message import ToolCall
    from llm_loop.llm.client import LLMResponse

    class InvalidThenContinue:
        def __init__(self, fixture, condition) -> None:
            self.fixture = fixture
            self.step = 0

        def chat_stream(self, messages, tools, **kwargs):
            self.step += 1
            if self.step == 1:
                resp = LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(id="bad-ref", name="read_evidence", arguments={"ref": "not-a-ref"})
                    ],
                    provider="fake",
                )
            elif self.step == 2:
                resp = LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="source-after-error",
                            name=self.fixture.source_tool,
                            arguments={"source": self.fixture.source_id},
                        )
                    ],
                    provider="fake",
                )
            else:
                resp = LLMResponse(
                    content=json.dumps({"answer": self.fixture.answer}),
                    tool_calls=[],
                    provider="fake",
                )
            if False:
                yield None
            return resp

    monkeypatch.setattr(runner, "FakeR2LLM", InvalidThenContinue)
    result = runner.execute_run(_row("F1", "E1"), dry=True)
    assert result["status"] == "COMPLETED"
    assert result["infra_error"] is None
    assert result["evidence_hydration_attempt_count"] == 1
    assert result["evidence_hydration_count"] == 0
    assert result["source_execution_count"] == 1
    assert any(x["kind"] == "hydrate_error" for x in result["trace"])
