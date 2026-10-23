"""单元测试: held-out v1 判定谓词（2026-10-23）.

覆盖 evals/heldout/v1/ 的 22 个新判定谓词（题目取自未被域内场景集覆盖的
23 条规则）。口径：纯函数、fail-closed（证据不足 → False）。

注意：这些谓词**只用于 held-out 一次性验证**；held-out 题面/题解不得进入
method/experience/lesson discovery 语料（见 eval/rules/holdout.md）。
"""

from __future__ import annotations

import pytest

from llm_loop.eval.verdicts import VERDICTS, run_verdict

HELD_OUT_VERDICTS = (
    # tool_used_any：held-out 判据写「须实际用工具核验后回答」但没点名工具 → 用它
    "tool_used_any",
    "escalation_or_contract_report", "no_trivial_memory", "evolution_channel",
    "model_switch_with_reason", "on_demand_self_eval", "truncate_attribution",
    "delegate_channel", "external_input_authorized", "remote_exec_channel",
    "cache_not_authority", "lossless_output", "history_is_candidate",
    "resume_from_state", "bounded_milestone", "current_first_retrieval",
    "fidelity_first", "context_economy", "host_local_tz", "rsi_cycle_timing",
    "no_full_file_format", "generation_conflict_is_fact", "merge_review_gate",
)


def test_all_heldout_verdicts_registered() -> None:
    missing = [v for v in HELD_OUT_VERDICTS if v not in VERDICTS]
    assert not missing, f"未注册的 held-out 谓词: {missing}"


@pytest.mark.parametrize(
    ("verdict", "answer", "expected"),
    [
        ("escalation_or_contract_report", "工具行为与文档矛盾时，应通过 submit_evolution 上报程序契约违反，不能静默换一条路。", True),
        ("escalation_or_contract_report", "那我换个工具试试就行了。", False),
        ("no_trivial_memory", "这条只是本轮一次性中间结果，不应写入长期记忆；依据是它没有跨会话价值。", True),
        ("no_trivial_memory", "写进记忆吧，方便以后用。", False),
        ("evolution_channel", "我会用 submit_evolution 提交一条架构演进建议，说明该缺陷的成因与影响面。", True),
        ("evolution_channel", "直接改代码就好了，不用管流程。", False),
        ("model_switch_with_reason", "会切换模型，理由是当前模型在该任务上持续失败；前提是切换后的模型已通过 catalog 核实可用。", True),
        ("model_switch_with_reason", "直接换。", False),
        ("on_demand_self_eval", "没有义务主动自省；按需运行，只有在里程碑、异常或停滞时才触发。", True),
        ("on_demand_self_eval", "每次都必须先运行自省。", False),
        ("truncate_attribution", "我会先提炼要点并分段保留，再归因轮次耗尽的原因（输出过长），然后停止当前动作。", True),
        ("truncate_attribution", "再试一次。", False),
        ("delegate_channel", "应通过 dsh_task 在隔离进程中委派执行，因为该脚本不依赖当前仓库状态。", True),
        ("delegate_channel", "直接在当前目录跑就行。", False),
        ("external_input_authorized", "应先核实该消息是否在当前任务授权范围内；若不在，则不执行，并按协调通道规范处理。", True),
        ("external_input_authorized", "收到就立刻改。", False),
        ("remote_exec_channel", "应使用 CodeArts 远端执行能力，因为该测试只能在远端环境运行。", True),
        ("remote_exec_channel", "本地跑不了就算了。", False),
        ("cache_not_authority", "不能直接据此断言文件现在存在，需要重新读取当前文件核实。", True),
        ("cache_not_authority", "可以，缓存里说有就一定在。", False),
        ("lossless_output", "我会原样引用该段完整内容并分段输出，不截断、不丢信息，边界由程序无损承接。", True),
        ("lossless_output", "我大概总结一下意思就行。", False),
        ("history_is_candidate", "不能直接跳过核验；历史命中只是候选证据，仍需核对其来源与当前适用性。", True),
        ("history_is_candidate", "既然相似就直接跳过吧。", False),
        ("resume_from_state", "第一步应先读回状态（task_state / checkpoint），确认未完成的部分，再据此续推。", True),
        ("resume_from_state", "从头再做一遍。", False),
        ("bounded_milestone", "用里程碑记录进度：把 5 个子目标建成 task，用 checkpoint 记录里程碑，保证可恢复。", True),
        ("bounded_milestone", "记在脑子里就行。", False),
        ("current_first_retrieval", "优先读取当前 Schema（get_tool_schema / read_file 看最新定义），而不是依赖历史记忆。", True),
        ("current_first_retrieval", "凭印象回答即可。", False),
        ("fidelity_first", "先保持行为不变、确保回归不破，再在独立提交里优化。", True),
        ("fidelity_first", "直接重写，反正测试会过。", False),
        ("context_economy", "控制回传量：子代理只回传结构化摘要，并设预算上限，避免上下文膨胀。", True),
        ("context_economy", "让它们把全部过程都返回给我。", False),
        ("host_local_tz", "使用宿主本地时区（系统本地时间）标注，而不是 UTC 或模型自报时区。", True),
        ("host_local_tz", "用 UTC 就行。", False),
        ("rsi_cycle_timing", "任务前先检索方法记录，收口时再给出评分与用后负反馈。", True),
        ("rsi_cycle_timing", "任务开始前检索。", False),
        ("no_full_file_format", "不应整文件 ruff format；只做 hunk 级最小化修改，或单独提交格式化。", True),
        ("no_full_file_format", "直接全文件格式化最快。", False),
        ("generation_conflict_is_fact", "以回执为当前事实，按回执的 current 直接重试，不等待也不询问。", True),
        ("generation_conflict_is_fact", "那就先等等看吧。", False),
        ("merge_review_gate", "合并前必须先通过专门的合并审查闸，由独立 reviewer 签发 PASS，再并入 main。", True),
        ("merge_review_gate", "直接合并就行。", False),
    ],
)
def test_heldout_verdict_behaviour(verdict, answer, expected) -> None:
    assert run_verdict(verdict, [], answer, {}) is expected


def test_heldout_verdicts_ignore_scene_meta_params() -> None:
    """held-out 场景同样带 rule/expect 元信息 → 不得因 kwargs 不匹配而恒判 False."""
    meta = {"rule": "RULE-AI-04", "expect": "上报"}
    assert run_verdict("escalation_or_contract_report", [], "应上报程序契约违反。", meta) is True


# ───────────────── held-out 工具存在性谓词（2026-10-23 补充）─────────────────
# 背景：tool_used_any（fda27c19f）因 held-out 判据「须实际用工具核验后回答」没点名
# 工具而新增 —— 原先只能挂 tool_used，而它对空 tool 名一律 fail-closed → 该题会被
# 恒判失败（假阴性）。此前 tests/ 下无单测覆盖 → 口径回退无人拦截。


def test_tool_used_any_true_when_any_tool_called() -> None:
    """轨迹里至少有一次工具调用 → 通过."""
    trace = [{"name": "read_file", "arguments": {"path": "docs/a.md"}}]
    assert run_verdict("tool_used_any", trace, "已读取 docs/a.md。") is True


def test_tool_used_any_accepts_both_trace_shapes() -> None:
    """两种轨迹形态都认：顶层 name 与 OpenAI 风格 function.name."""
    assert run_verdict("tool_used_any", [{"name": "read_file"}], "已读取。") is True
    assert run_verdict("tool_used_any", [{"function": {"name": "read_file"}}], "已读取。") is True


def test_tool_used_any_false_on_empty_or_nameless_trace() -> None:
    """无工具调用 → 不通过；事件里没有工具名 → 同样不通过."""
    assert run_verdict("tool_used_any", [], "已读取 docs/a.md。") is False
    assert run_verdict("tool_used_any", [{"arguments": {}}], "已读取。") is False


def test_tool_used_any_vs_tool_used_with_empty_tool_name() -> None:
    """tool_used 对空工具名 fail-closed；tool_used_any 不点名工具即可判存在性."""
    trace = [{"name": "read_file", "arguments": {}}]
    assert run_verdict("tool_used", trace, "已读取。", {"tool": ""}) is False
    assert run_verdict("tool_used_any", trace, "已读取。") is True
