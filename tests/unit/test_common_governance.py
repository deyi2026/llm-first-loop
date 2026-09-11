from __future__ import annotations

from hashlib import sha256

from llm_loop.core.prompt import build_system_prompt


def test_common_governance_prefix_is_deterministic_and_bounded():
    a = build_system_prompt()
    b = build_system_prompt()
    assert a == b
    assert len(a) < 200
    assert sha256(a.encode()).hexdigest() == sha256(b.encode()).hexdigest()


def test_common_governance_encodes_reusable_anti_drift_invariants():
    prompt = build_system_prompt()
    expected = (
        "保持目标约束",
        "区分事实/假设",
        "无新反证不重复核验",
        "只查会改变下一步的不确定性",
        "优先当前证据",
        "历史经验按需",
        "中断后先接最近未完成状态",
    )
    for item in expected:
        assert item in prompt


def test_current_truth_and_authority_remain_primary():
    prompt = build_system_prompt()
    assert "当前用户指令是任务授权真值" in prompt
    assert "不得升级为当前任务" in prompt


def test_common_governance_does_not_restore_prompt_heavy_playbooks():
    prompt = build_system_prompt()
    forbidden = (
        "HOT / WARM / COLD", "Adaptive Autonomy", "Tier 0", "Tier 1",
        "Tier 2", "Tier 3", "每轮自查", "submit_evolution", "self_evaluate",
        "architecture_status", "search_archive", "save_experience", "增量推理",
    )
    for item in forbidden:
        assert item not in prompt
