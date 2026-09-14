from __future__ import annotations

from hashlib import sha256

from llm_loop.core.prompt import build_system_prompt


def test_common_governance_prefix_is_deterministic_and_bounded():
    a = build_system_prompt()
    b = build_system_prompt()
    assert a == b
    assert len(a) < 400
    assert sha256(a.encode()).hexdigest() == sha256(b.encode()).hexdigest()


def test_current_evidence_invariant_has_one_structured_core_anchor():
    prompt = build_system_prompt()
    invariant = (
        "涉及当前代码、文件、路径、版本、运行态、配置或外部接口等可核事实时，"
        "训练先验/历史知识只作假设，先取当前证据；无法核对就明示未核验，不猜。"
    )

    assert prompt.count("[LFL核心认知]") == 1
    assert prompt.count(invariant) == 1
    assert prompt.endswith(f"[LFL核心认知]\n{invariant}")
    assert len(prompt) == 380
    assert sha256(prompt.encode()).hexdigest() == (
        "8934d96c3f25a6727df750e3f73e0ed73743c985b861d97f7bc3f7f2a4c60392"
    )


def test_common_governance_encodes_reusable_anti_drift_invariants():
    prompt = build_system_prompt()
    expected = (
        "保持目标约束",
        "区分事实/假设",
        "训练先验/历史知识只作假设",
        "先取当前证据",
        "无法核对就明示未核验",
        "未获成功回执不得声称完成",
        "参数失败时先核当前 Schema/代码/文档再修正",
        "已验证经验/方法并核适用性",
        "无新反证不重复核验",
        "只查会改变下一步的不确定性",
        "中断后先接最近未完成状态",
        "已确立事实、未解决问题和本步动作",
    )
    for item in expected:
        assert item in prompt


def test_epistemic_honesty_is_universal_not_local_model_guidance():
    prompt = build_system_prompt()
    for current_fact in ("当前代码", "文件", "路径", "版本", "运行态", "配置", "外部接口"):
        assert current_fact in prompt
    for local_only in ("Ornith", "Qwen", "cognilocal", "GLM", "MiniMax", "DeepSeek"):
        assert local_only not in prompt


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
