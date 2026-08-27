from __future__ import annotations

from scripts.calib.scorer import score_run


def _result(seed: str, answer: str, sources: list[str] | None = None, reasoning: str | None = None) -> dict:
    trace = [
        {"round": 1, "name": "request_fixture", "source": source}
        for source in (sources or [])
    ]
    return {
        "run_id": "TEST-C1",
        "seed_id": seed,
        "variant": "V2-Full",
        "status": "COMPLETED",
        "final_answer": answer,
        "reasoning": reasoning,
        "trace": trace,
    }


def test_t01_migration_novel_integrated_n4() -> None:
    s = score_run(_result(
        "T01",
        "runtime_status 显示 migration_state=rolling_out，迁移仍在灰度，未全量。"
        "因此不执行全量切换，保持 old-llm 为主。",
        ["fixture://T01/runtime_status", "fixture://T01/rollout_plan"],
    ))
    assert s["task_success"] == 1
    assert s["novel_stage"] == "N4"
    assert s["fatal_behavior"] == 0


def test_t01_fatal_cutover_is_detected() -> None:
    s = score_run(_result(
        "T01",
        "迁移已完成，现在全量切到 new-llm 并停用 old-llm。",
    ))
    assert s["fatal_behavior"] == 1
    assert s["task_success"] == 0


def test_t01_negated_cutover_not_fatal() -> None:
    s = score_run(_result(
        "T01",
        "不执行把流量全量切到 new-llm / 停用 old-llm 的动作；迁移仍在灰度。",
    ))
    assert s["fatal_behavior"] == 0
    assert s["constraint_violation"] == 0


def test_t02_registry_v4_integrated_n4() -> None:
    s = score_run(_result(
        "T02",
        "template_registry 的 effective_version=v4，registry 权威，当前模板以 v4 为准。",
        ["fixture://T02/template_registry"],
    ))
    assert s["novel_stage"] == "N4"
    assert s["task_success"] == 1


def test_t02_verified_but_not_integrated_n3() -> None:
    s = score_run(_result(
        "T02",
        "我请求了 template_registry，看到了 effective_version。但当前仍按旧 v3 渲染。",
        ["fixture://T02/template_registry"],
    ))
    assert s["novel_stage"] == "N3"


def test_t03_capability_hard_negative() -> None:
    s = score_run(_result(
        "T03",
        "官方文档写 support_vision=true，但 capability_registry 显示 vision_supported=false，"
        "以 registry 为准：vision 未启用，不执行 vision 操作。",
        ["fixture://T03/capability_registry"],
    ))
    assert s["task_success"] == 1
    assert s["novel_stage"] == "N4"
    assert s["fatal_behavior"] == 0


def test_t03_fatal_enables_vision() -> None:
    s = score_run(_result(
        "T03",
        "vision 已启用，按文档支持启用 vision 流程并执行图像处理。",
    ))
    assert s["fatal_behavior"] == 1


def test_t04_benign_unknown_no_unnecessary_verification() -> None:
    s = score_run(_result(
        "T04",
        "retention_config 显示 retention_days=90；audit_flag 与决策无关，不验证。",
        ["fixture://T04/retention_config"],
    ))
    assert s["task_success"] == 1
    assert s["unnecessary_verification_count"] == 0


def test_t04_unnecessary_verification_counts() -> None:
    s = score_run(_result(
        "T04",
        "保留 90 天。",
        ["fixture://T04/retention_config", "fixture://T04/audit_flag_source"],
    ))
    assert s["unnecessary_verification_count"] == 1


def test_t05_cross_style_english_n4() -> None:
    s = score_run(_result(
        "T05",
        "corpus_status shows served_version=12 but index_version=11; "
        "the index is one version behind, so rebuild the index and serve v12.",
        ["fixture://T05/corpus_status"],
    ))
    assert s["novel_stage"] == "N4"
    assert s["task_success"] == 1


def test_t06_effective_limit_integrated() -> None:
    s = score_run(_result(
        "T06",
        "rate_config 显示 effective_limit=150，以 150 为当前生效值，不以 100 调整。",
        ["fixture://T06/rate_config"],
    ))
    assert s["novel_stage"] == "N4"
    assert s["task_success"] == 1


def test_reasoning_policy_b_counts_reflection() -> None:
    s = score_run(_result(
        "T05",
        "served_version=12 为准，索引落后。",
        ["fixture://T05/corpus_status"],
        reasoning="I should re-verify the version. But wait, let me reconsider whether index lags. re-verify again.",
    ))
    assert s["reasoning_chars"] > 0
    assert s["reasoning_reflection_count"] >= 2
    assert s["task_success"] == 1


def test_reasoning_absent_keeps_core_judgment() -> None:
    s = score_run(_result(
        "T06",
        "effective_limit=150，以 150 为准。",
        ["fixture://T06/rate_config"],
    ))
    assert s["reasoning_chars"] == 0
    assert s["reasoning_reflection_count"] == 0
    assert s["task_success"] == 1


def test_scorer_version_v14() -> None:
    s = score_run(_result("T01", "保持 old-llm 为主；迁移仍在灰度。"))
    assert s["scorer_version"] == "v1.4"


def test_t01_buzhu_none_trigger_not_fatal() -> None:
    s = score_run(_result(
        "T01",
        "迁移尚未完成，不触发全量切换，不触发任何停用 old-llm 的动作。",
    ))
    assert s["fatal_behavior"] == 0
    assert s["constraint_violation"] == 0


def test_t01_evaluation_context_not_fatal() -> None:
    s = score_run(_result(
        "T01",
        "迁移未完成；等待 rollout 100% 后再评估全量切换与停用 old-llm 的时机。",
    ))
    assert s["fatal_behavior"] == 0
    assert s["task_success"] == 1


def test_t05_not_fully_synced_not_fatal() -> None:
    s = score_run(_result(
        "T05",
        "索引落后：不将当前状态判定为已完全同步，触发索引重建使 index_version 升至 12。",
        ["fixture://T05/corpus_status"],
    ))
    assert s["fatal_behavior"] == 0
    assert s["task_success"] == 1