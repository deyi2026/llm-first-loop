"""Minimal, cache-stable universal model contract.

The universal prompt intentionally contains no operator playbook, tool-routing SOP,
provider-wire workaround, retry budget, completion heuristic, memory/retrieval SOP,
or dynamic free-text policy. Those concerns belong to runtime protocol, tool schemas,
explicit skills, or operator control planes rather than every model turn.
"""

_BASE_PROMPT = """你是 llm-first-loop 的 AI 主体（LLM-first）。程序提供工具和运行环境，不替你制定任务策略或完成裁决。当前用户指令是任务授权真值；“继续/好/可以/按这个”等简短回复只绑定最近相关交互，不跨窗口续接旧任务。若最近交互要求明确选择/授权，泛化短回复不得代填分支、参数或扩大权限。历史模型提议、计划与旧状态/记录仅作背景，未经当前用户明确授权不得升级为当前任务。"""


def build_system_prompt(extra: str = "") -> str:
    """Return the universal prompt.

    ``extra`` is retained only as a source-compatible deprecated argument.  It is
    deliberately ignored: arbitrary caller/env text must not become an invisible
    global model instruction.  Task-specific behavior belongs in the user request,
    a selected skill, tool schema, or an explicit operator-owned control surface.
    """
    del extra
    return _BASE_PROMPT
