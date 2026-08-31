"""R8.24-E E-4.2 锚定: CORE9 A/B 评估脚本可回放 + 判据断言（§13.2 硬门）."""

from __future__ import annotations


def test_core_ab_eval_matrix_runs_and_gate_holds():
    from scripts.core_ab_eval import evaluate

    result = evaluate()
    plans = result["plans"]
    assert set(plans) == {
        "plan_i_status_quo",
        "plan_ii_reduced",
        "plan_iii_recovery_full",
        "plan_iii_recovery_half",
    }
    # §13.2 硬门: 缩减后 capability discovery 成功率不下降（完成率 ≥ 现状基线）
    assert plans["plan_ii_reduced"]["completion_rate"] >= plans["plan_i_status_quo"]["completion_rate"]
    # 四指标齐备
    for m in plans.values():
        for key in (
            "completion_rate",
            "misdirected_tool_rate",
            "avg_discovery_rounds_per_hidden_tool",
            "total_schema_lookups",
        ):
            assert key in m
    # 扩入方向 lookup 恒 ≤ 现状（恢复三件套在 CORE 消除截断轮目录查询）
    assert plans["plan_iii_recovery_full"]["total_schema_lookups"] <= plans["plan_i_status_quo"]["total_schema_lookups"]
    # 验证等级标注在场（fixture 回放替代——不虚报）
    assert "fixture" in result["verification_level"]
