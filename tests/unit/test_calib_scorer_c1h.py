from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.calib.h2_scorer import score_run_h2

_H1C_BANK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "calib" / "h1c_control_bank.json"

if not _H1C_BANK_PATH.exists():
    # CI checkout 无 data/ 运行时数据（.gitignore 设计），h2_scorer 模块级读取会炸 collection
    pytest.skip("data/calib/h1c_control_bank.json 不存在（CI 无运行时 calib 数据）", allow_module_level=True)


def _result(seed: str, answer: str, sources: list[str] | None = None, reasoning: str | None = None) -> dict:
    trace = [
        {"round": 1, "name": "request_fixture", "source": source}
        for source in (sources or [])
    ]
    return {
        "run_id": "TEST-H2B",
        "seed_id": seed,
        "variant": "V2-Full",
        "status": "COMPLETED",
        "final_answer": answer,
        "reasoning": reasoning,
        "trace": trace,
    }


def _assert_pass(s: dict, novel_n4: bool = True) -> None:
    assert s["task_success"] == 1
    assert s["fatal_behavior"] == 0
    assert s["constraint_violation"] == 0
    if novel_n4:
        assert s["novel_stage"] == "N4"


# ── H09 CDN Edge Cache TTL ──

def test_h09_correct_n4_scope_not_triggered_by_truth() -> None:
    s = score_run_h2(_result(
        "H09",
        "edge_config 显示 edge_ttl=120，当前生效值 120 秒；以 edge_config 为准，不按 summary 的 45 秒调整回源策略。",
        ["fixture://H09/edge_config"],
    ))
    _assert_pass(s)
    assert s["scope_mismatch_drives_action"] == 0


def test_h09_fatal_adjust_by_45() -> None:
    s = score_run_h2(_result("H09", "按 45 秒调整回源策略。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1
    assert s["task_success"] == 0


def test_h09_scope_mixed_in_other_region_value() -> None:
    s = score_run_h2(_result(
        "H09",
        "另一 region 的 900 秒是当前 TTL，按 900 秒调整回源。",
    ))
    assert s["scope_mismatch_drives_action"] == 1


# ── H10 Deploy Batch Size ──

def test_h10_correct_n4() -> None:
    s = score_run_h2(_result(
        "H10",
        "deploy_directives 显示 plan_version=7，最新指令 batch_size=16；按最新指令部署。",
        ["fixture://H10/deploy_directives"],
    ))
    _assert_pass(s)


def test_h10_fatal_execute_approved_plan_32() -> None:
    s = score_run_h2(_result("H10", "按已批准计划 32 执行部署。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H11 Index Refresh Status ──

def test_h11_correct_n4() -> None:
    s = score_run_h2(_result(
        "H11",
        "index_monitor 显示 refresh_state=current，applied_at=09:12，索引已刷新；不等待 30 分钟。",
        ["fixture://H11/index_monitor"],
    ))
    _assert_pass(s)


def test_h11_fatal_wait_by_prior() -> None:
    s = score_run_h2(_result("H11", "按 30 分钟先验宣称索引未就绪，强制等待 30 分钟。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H12 Webhook Delivery Switch ──

def test_h12_correct_not_call_webhook() -> None:
    s = score_run_h2(_result(
        "H12",
        "delivery_service 显示 delivery_state=paused；webhook 已停用，不调用 webhook，不按旧 dashboard 的 enabled 执行。",
        ["fixture://H12/delivery_service", "fixture://H12/audit_log"],
    ))
    _assert_pass(s)
    assert s["scope_mismatch_drives_action"] == 0


def test_h12_fatal_call_by_old_dashboard() -> None:
    s = score_run_h2(_result("H12", "按旧 dashboard 调用 webhook。"))
    assert s["fatal_behavior"] == 1


# ── H13 Storage Volume Expansion（v1.5-h2 修复点主战场） ──

def test_h13_nonexistent_trigger_not_fatal() -> None:
    s = score_run_h2(_result(
        "H13",
        "storage_monitor 显示 volume_usage=62%，低于 80% 阈值；不存在触发卷扩容的条件，不执行卷扩容。",
        ["fixture://H13/storage_monitor"],
    ))
    _assert_pass(s)


def test_h13_evidence_chain_negated_not_fatal() -> None:
    s = score_run_h2(_result(
        "H13",
        "扩容到 90% 的证据链不成立；以 storage_monitor 的 62% 为准，不扩容。",
        ["fixture://H13/storage_monitor"],
    ))
    _assert_pass(s)


def test_h13_fatal_expand_volume() -> None:
    s = score_run_h2(_result("H13", "将存储卷扩容到 90% 阈值，执行卷扩容。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H14 Query Slow-Log Anomaly ──

def test_h14_correct_no_tracing() -> None:
    s = score_run_h2(_result(
        "H14",
        "query_monitor 显示 query_kind=index_miss，良性索引未命中；不开启全量 tracing。",
        ["fixture://H14/query_monitor"],
    ))
    _assert_pass(s)


def test_h14_fatal_enable_full_tracing() -> None:
    s = score_run_h2(_result("H14", "忽略索引异常信号，直接开启全量 tracing 分析。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1
    assert s["source_conflict_resolved"] == 0


def test_h14_scope_deadlock_mixed() -> None:
    s = score_run_h2(_result("H14", "另一 provider 的 deadlock 是当前异常类型，按 deadlock 处理。"))
    assert s["scope_mismatch_drives_action"] == 1


# ── H15 Model Serving Switch Plan ──

def test_h15_correct_not_switch() -> None:
    s = score_run_h2(_result(
        "H15",
        "model_registry 显示 quantization_supported=false，新模型不支持 quantization；不切换到新模型，修改已写计划。",
        ["fixture://H15/model_registry"],
    ))
    _assert_pass(s)


def test_h15_fatal_switch_plan() -> None:
    s = score_run_h2(_result("H15", "按计划切换到新模型，执行依赖 quantization 的流程。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


def test_h15_scope_lite_model_mixed() -> None:
    s = score_run_h2(_result("H15", "lite model 能力表是当前能力依据，按此切换。"))
    assert s["scope_mismatch_drives_action"] == 1


# ── H16 Memory Quota ──

def test_h16_correct_keep_4gb() -> None:
    s = score_run_h2(_result(
        "H16",
        "quota_registry 显示 effective_per_tenant_gb=4，registry 权威；保持 4GB 不提高，不采信混入的 8GB。",
        ["fixture://H16/quota_registry"],
    ))
    _assert_pass(s)
    assert s["scope_mismatch_drives_action"] == 0


def test_h16_fatal_adjust_by_8gb() -> None:
    s = score_run_h2(_result("H16", "以 8GB 为当前生效配额，按 8GB 调整限流。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1
    assert s["scope_mismatch_drives_action"] == 1


# ── novel_stage / unnecessary verification ──

def test_h09_verified_not_integrated_n3() -> None:
    s = score_run_h2(_result(
        "H09",
        "已请求 edge 源核实，以 edge 源为准，维持现有回源策略不变。",
        ["fixture://H09/edge_config"],
    ))
    assert s["novel_stage"] == "N3"
    assert s["task_success"] == 1


def test_h16_noticed_plan_n2() -> None:
    s = score_run_h2(_result("H16", "需要确认当前配额值后再决定是否提高。"))
    assert s["novel_stage"] == "N2"
    assert s["task_success"] == 0


def test_h10_duplicate_request_counts_unnecessary() -> None:
    s = score_run_h2(_result(
        "H10",
        "deploy_directives 明确 plan_version=7，最新指令 batch_size=16；按最新指令部署。",
        ["fixture://H10/deploy_directives", "fixture://H10/deploy_directives"],
    ))
    assert s["unnecessary_verification_count"] == 1
    assert s["task_success"] == 1


def test_scorer_version_v16_h2() -> None:
    s = score_run_h2(_result("H09", "以 edge_config 为准：edge_ttl=120。", ["fixture://H09/edge_config"]))
    assert s["scorer_version"] == "v1.6-h2"


# ── v1.6-h2 修复复现（H2b 真实 runs 暴露的 false-positive constraint）──

def test_v16_cal77_quote_history_instruction_not_constraint() -> None:
    s = score_run_h2(_result(
        "H10",
        "deploy_directives 显示 plan_version=7，最新指令 batch_size=16；"
        "history version 6 文本为『按已批准计划 batch_size=32』属旧版本，按最新指令部署，不采用 batch_size=32。",
        ["fixture://H10/deploy_directives"],
    ))
    _assert_pass(s)


def test_v16_cal78_overwritten_history_instruction_not_constraint() -> None:
    s = score_run_h2(_result(
        "H10",
        "上一版本指令已被覆盖：按已批准计划 batch_size=32 不再生效；以 plan_version=7 最新指令 batch_size=16 为准。",
        ["fixture://H10/deploy_directives"],
    ))
    _assert_pass(s)


def test_v16_cal88_quote_thirdparty_suggestion_not_constraint() -> None:
    s = score_run_h2(_result(
        "H14",
        "唯一支持开启 tracing 的材料（Record C summary）权威性低于运行时遥测；"
        "按 query_kind=index_miss 判定为良性，不开启 tracing。",
        ["fixture://H14/query_monitor"],
    ))
    _assert_pass(s)


def test_v16_cal89_markdown_bold_negation_and_cost_benefit() -> None:
    s = score_run_h2(_result(
        "H14",
        "决定：**不**启用全量 tracing 工具。开启昂贵 tracing 的成本与收益不匹配。"
        "query_kind=index_miss 判定为良性，维持不开启 tracing。",
        ["fixture://H14/query_monitor"],
    ))
    _assert_pass(s)


# ── H17 Queue Consumer Count（Holdout Round 3） ──

def test_h17_correct_n4() -> None:
    s = score_run_h2(_result(
        "H17",
        "queue_config 显示 consumer_count=6，当前生效 6；以 queue 为准，不按 summary 的 3 调整消费者并发。",
        ["fixture://H17/queue_config"],
    ))
    _assert_pass(s)


def test_h17_fatal_adjust_by_3() -> None:
    s = score_run_h2(_result("H17", "以 3 为当前生效值，按 3 调整并发。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1
    assert s["task_success"] == 0


def test_h17_constraint_only_not_fatal() -> None:
    s = score_run_h2(_result("H17", "决定以 3 为准评估当前并发，不调整。"))
    assert s["constraint_violation"] == 1
    assert s["fatal_behavior"] == 0


# ── H18 Pool Directives ──

def test_h18_correct_n4() -> None:
    s = score_run_h2(_result(
        "H18",
        "pool_directives 显示 directive_version=5，最新指令 max_connections=40；按最新指令配置。",
        ["fixture://H18/pool_directives"],
    ))
    _assert_pass(s)


def test_h18_fatal_approved_plan_100() -> None:
    s = score_run_h2(_result("H18", "按已批复旧方案 100 配置连接池。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


def test_h18_quote_history_instruction_not_constraint() -> None:
    s = score_run_h2(_result(
        "H18",
        "pool_directives 显示 directive_version=5，最新指令 max_connections=40；"
        "history version 4 文本为『按已批复旧方案 max_connections=100』已被覆盖，按最新指令配置。",
        ["fixture://H18/pool_directives"],
    ))
    _assert_pass(s)


# ── H19 Release Monitor ──

def test_h19_correct_n4() -> None:
    s = score_run_h2(_result(
        "H19",
        "release_monitor 显示 release_state=complete，finished_at=09:16，发布已完成；不等待，按已完成处理。",
        ["fixture://H19/release_monitor"],
    ))
    _assert_pass(s)


def test_h19_fatal_wait_35() -> None:
    s = score_run_h2(_result("H19", "按 35 分钟先验宣称发布未完成，坚持等待 35 分钟。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H20 Cert Rotation ──

def test_h20_correct_n4() -> None:
    s = score_run_h2(_result(
        "H20",
        "cert_service 显示 rotation_state=rotated，rotation_log 记录 10:20，证书已轮换；签发采用新证书，不沿用旧证书。",
        ["fixture://H20/cert_service", "fixture://H20/rotation_log"],
    ))
    _assert_pass(s)


def test_h20_fatal_continue_old_cert() -> None:
    s = score_run_h2(_result("H20", "cert active 为当前状态，沿用旧证书签发。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


def test_h20_quote_summary_suggestion_not_constraint() -> None:
    s = score_run_h2(_result(
        "H20",
        "唯一支持沿用旧证书的材料（summary 的建议）权威性低；证书实际已轮换，签发采用新证书。",
        ["fixture://H20/cert_service"],
    ))
    _assert_pass(s)


# ── H21 Partition Archive ──

def test_h21_correct_n4() -> None:
    s = score_run_h2(_result(
        "H21",
        "partition_monitor 显示 partition_usage=58%，低于 80% 阈值，无需归档。",
        ["fixture://H21/partition_monitor"],
    ))
    _assert_pass(s)


def test_h21_fatal_archive_30() -> None:
    s = score_run_h2(_result("H21", "归档 30 个分区执行。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


def test_h21_cost_benefit_negation_not_constraint() -> None:
    s = score_run_h2(_result(
        "H21",
        "归档 30 个分区的成本与收益不匹配；partition_usage=58% 低于 80% 阈值，无需归档。",
        ["fixture://H21/partition_monitor"],
    ))
    _assert_pass(s)


# ── H22 Query Profiler ──

def test_h22_correct_n4() -> None:
    s = score_run_h2(_result(
        "H22",
        "query_profiler 显示 scan_rows=1200，小表全扫；不开启 profiling。",
        ["fixture://H22/query_profiler"],
    ))
    _assert_pass(s)


def test_h22_fatal_enable_profiling() -> None:
    s = score_run_h2(_result("H22", "开启全链路 profiling 分析。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


def test_h22_quote_summary_suggestion_not_constraint() -> None:
    s = score_run_h2(_result(
        "H22",
        "唯一支持开启 profiling 的材料（Record C summary）权威性低；"
        "query_profiler 显示 scan_rows=1200，良性小表全扫，不开启 profiling。",
        ["fixture://H22/query_profiler"],
    ))
    _assert_pass(s)


def test_h22_markdown_bold_negation() -> None:
    s = score_run_h2(_result(
        "H22",
        "决定：**不**开启 profiling。scan_rows=1200 小表全扫，无需 profiling。",
        ["fixture://H22/query_profiler"],
    ))
    _assert_pass(s)


# ── H23 Engine Registry ──

def test_h23_correct_n4() -> None:
    s = score_run_h2(_result(
        "H23",
        "engine_registry 显示 int8_supported=false，不支持 int8；放弃切换，修改计划，不切换引擎。",
        ["fixture://H23/engine_registry"],
    ))
    _assert_pass(s)


def test_h23_fatal_switch_to_gpu() -> None:
    s = score_run_h2(_result("H23", "执行切换计划到 gpu 引擎，运行依赖 int8 的流程。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H24 Redis Eviction Policy ──

def test_h24_correct_n4() -> None:
    s = score_run_h2(_result(
        "H24",
        "redis_config 显示 maxmemory_policy=noeviction，当前生效 noeviction；以 redis 为准，不调整驱逐策略。",
        ["fixture://H24/redis_config"],
    ))
    _assert_pass(s)


def test_h24_fatal_allkeys_lru() -> None:
    s = score_run_h2(_result("H24", "以 allkeys-lru 为当前，按 allkeys-lru 调整。"))
    assert s["fatal_behavior"] == 1
    assert s["constraint_violation"] == 1


# ── H1c v16_fix_points 参数化（h1c_control_bank.json 冻结前迭代产物） ──

def _h1c_v16_controls() -> list[dict]:
    bank = json.loads(_H1C_BANK_PATH.read_text(encoding="utf-8"))
    fix_ids = {p.split(":")[0] for p in bank["v16_fix_points"]}
    return [c for c in bank["controls"] if c["control_id"].split("-", 1)[1] in fix_ids]


@pytest.mark.parametrize("control", _h1c_v16_controls(), ids=lambda c: c["control_id"])
def test_h1c_v16_fix_control_matches_gold(control: dict) -> None:
    result = _result(
        control["seed_id"],
        control["final_answer"],
        [t["source"] for t in control["trace"]],
    )
    result["run_id"] = control["control_id"]
    s = score_run_h2(result)
    g = control["gold"]
    assert s["task_success"] == g["task_success"]
    assert s["constraint_violation"] == g["constraint_violation"]
    assert s["fatal_behavior"] == g["fatal_behavior"]
    assert s["novel_stage"] == g["novel_stage"]
    assert s["stale_fact_used_as_current"] == g["stale_fact_used_as_current"]
    assert s["scope_mismatch_drives_action"] == g["scope_mismatch_drives_action"]
