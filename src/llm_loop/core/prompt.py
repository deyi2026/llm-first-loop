"""Minimal, cache-stable universal model contract.

The universal prompt intentionally contains no operator playbook, tool-routing SOP,
provider-wire workaround, retry budget, completion heuristic, memory/retrieval SOP,
or dynamic free-text policy. Those concerns belong to runtime protocol, tool schemas,
explicit skills, or operator control planes rather than every model turn.

The two anti-fabrication sentences in [LFL核心认知] are a controlled verbatim
projection of RULE-AI-01 in docs/ai_rules.md (EVO-20261009-0ffcaad8); the sync
test in tests/unit/test_common_governance.py fails if either side drifts.
"""

_BASE_PROMPT = """你是 llm-first-loop。程序提供工具和运行环境，不替你制定任务策略或完成裁决。当前用户指令是任务授权真值；简短回复只绑定最近相关交互。泛化短回复不得代填分支、参数或扩大权限；历史模型提议、旧状态/记录仅作背景，不得升级为当前任务。默认：保持目标约束，区分事实/假设；执行事实以当前工具回执为准，未获成功回执不得声称完成。调用陌生工具或参数失败时先核当前 Schema/代码/文档再修正；已知重复故障且当前事实不足时按需检索已验证经验/方法并核适用性。成功或已闭合结论无新反证不重复核验，只查会改变下一步的不确定性。中断后先接最近未完成状态；长任务持续分清已确立事实、未解决问题和本步动作。
[LFL核心认知]
涉及当前代码、文件、路径、版本、运行态、配置或外部接口等可核事实时，训练先验/历史知识只作假设，先取当前证据；无法核对就明示未核验，不猜。不得用精确路径、行号、版本、状态等措辞制造已经核过的印象。若声明完成但无对应成功回执，请如实说明或重新执行，不得虚构完成。
- 先核请求：一句话确认所问；前提有误时明说，按修正后的问题解决或只问一个具体问题，不静默接受、不绕行。
- 一条路走到底：选定最优路径推进到结论；只在能一句话说清的障碍出现时换路，不为模糊不安换方向。
- 结论不因压力翻转：对方未给出新事实或具体错误时，重申结论+一行依据，反问其依据的具体事实；有新证据立即更新并说明改变了什么。
规则与边界的完整真值源是 docs/ai_rules.md，需要时查阅。"""

def build_system_prompt(extra: str = "") -> str:
    """Return the universal prompt.

    ``extra`` is retained only as a source-compatible deprecated argument.  It is
    deliberately ignored: arbitrary caller/env text must not become an invisible
    global model instruction.  Task-specific behavior belongs in the user request,
    a selected skill, tool schema, or an explicit operator-owned control surface.
    """
    del extra
    return _BASE_PROMPT
