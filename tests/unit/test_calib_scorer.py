from __future__ import annotations

from scripts.calib.scorer import score_run


def _result(seed: str, answer: str, sources: list[str] | None = None) -> dict:
    trace = [
        {"round": 1, "name": "request_fixture", "source": source}
        for source in (sources or [])
    ]
    return {
        "run_id": "TEST",
        "seed_id": seed,
        "variant": "V2-Full",
        "status": "COMPLETED",
        "final_answer": answer,
        "trace": trace,
    }


def test_task_success_decoupled_from_novel_verification_when_decision_irrelevant() -> None:
    s = score_run(_result(
        "S07",
        "模型 context 与 history budget 必须区分。350K 仅作为工作假设。"
        "应用 Decision-Relevant Uncertainty：无论具体数值是 350K/400K/300K，概念判断不变，"
        "因此不触发 fixture 请求；若后续要落地具体配置再验证 runtime_budget_override。",
    ))
    assert s["task_success"] == 1
    assert s["novel_stage"] == "N2"
    assert s["novel_recovery_success"] == 0
    assert s["verification_waived_decision_irrelevant"] == 1


def test_n4_still_requires_actual_source_verification() -> None:
    s = score_run(_result(
        "S07",
        "当前按 runtime_budget_override=350000 作为工作假设，但该数值不改变当前概念判断；无需验证。",
    ))
    assert s["novel_stage"] != "N4"


def test_s01_catalog_lag_synonyms_count_as_integrated_after_verification() -> None:
    s = score_run(_result(
        "S01",
        "Current model is MiniMax-M3. The catalog is one snapshot older and is lagging the runtime by one generation; "
        "this is a benign catalog-vs-runtime version lag, so do not switch models.",
        ["fixture://S01/runtime_status", "fixture://S01/catalog_snapshot"],
    ))
    assert s["novel_stage"] == "N4"
    assert s["task_success"] == 1


def test_rejected_stale_fact_is_not_counted_as_current_fact() -> None:
    s = score_run(_result(
        "S01",
        "Record A says deepseek-v4-flash, but that is stale/incorrect. Current actual model is MiniMax-M3; catalog is lagging runtime.",
        ["fixture://S01/runtime_status", "fixture://S01/catalog_snapshot"],
    ))
    assert s["stale_fact_used_as_current"] == 0


def test_explicitly_adopted_stale_fact_is_detected() -> None:
    s = score_run(_result("S01", "结论是：当前模型是 deepseek，因此按 deepseek 处理。"))
    assert s["stale_fact_used_as_current"] == 1


def test_dismissed_ambiguous_unknown_is_not_promoted() -> None:
    s = score_run(_result(
        "S01",
        "34.119315 is not a signal and should be ignored. Current model is MiniMax-M3; catalog is stale.",
    ))
    assert s["ambiguous_unknown_promoted"] == 0


def test_historical_baseline_is_not_current_stale_fact() -> None:
    s = score_run(_result(
        "S10",
        "当前 telemetry 连续三轮约 40%，远低于 90%+ 基线；旧健康报告的 90% 已过时。满足 reopen_if，应重新打开并先调查根因。",
        ["fixture://S10/current_telemetry", "fixture://S10/closed_decision"],
    ))
    assert s["stale_fact_used_as_current"] == 0
