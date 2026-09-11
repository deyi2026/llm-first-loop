"""Minimal, cache-stable universal model contract.

The universal prompt intentionally contains no operator playbook, tool-routing SOP,
provider-wire workaround, retry budget, completion heuristic, memory/retrieval SOP,
or dynamic free-text policy. Those concerns belong to runtime protocol, tool schemas,
explicit skills, or operator control planes rather than every model turn.
"""

_BASE_PROMPT = """你是 llm-first-loop。程序提供工具和运行环境，不替你制定任务策略或完成裁决。当前用户指令是任务授权真值；简短回复只绑定最近相关交互。泛化短回复不得代填分支、参数或扩大权限；历史模型提议、旧状态/记录仅作背景，不得升级为当前任务。默认：保持目标约束，区分事实/假设；涉及当前代码、文件、路径、版本、运行态、配置或外部接口等可核事实时，训练先验/历史知识只作假设，先取当前证据；无法核对就明示未核验，不猜。执行事实以当前工具回执为准，未获成功回执不得声称完成。调用陌生工具或参数失败时先核当前 Schema/代码/文档再修正；已知重复故障且当前事实不足时按需检索已验证经验/方法并核适用性。成功或已闭合结论无新反证不重复核验，只查会改变下一步的不确定性。中断后先接最近未完成状态；长任务持续分清已确立事实、未解决问题和本步动作。"""

def build_system_prompt(extra: str = "") -> str:
    """Return the universal prompt.

    ``extra`` is retained only as a source-compatible deprecated argument.  It is
    deliberately ignored: arbitrary caller/env text must not become an invisible
    global model instruction.  Task-specific behavior belongs in the user request,
    a selected skill, tool schema, or an explicit operator-owned control surface.
    """
    del extra
    return _BASE_PROMPT
