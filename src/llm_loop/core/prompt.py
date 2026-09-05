"""Minimal, cache-stable universal model contract.

The universal prompt intentionally contains no operator playbook, tool-routing SOP,
provider-wire workaround, retry budget, completion heuristic, memory/retrieval SOP,
or dynamic free-text policy. Those concerns belong to runtime protocol, tool schemas,
explicit skills, or operator control planes rather than every model turn.
"""

_BASE_PROMPT = """你是 llm-first-loop 的 AI 主体（LLM-first）。程序提供工具和运行环境，不替你制定任务策略或完成裁决。"""


def build_system_prompt(extra: str = "") -> str:
    """Return the universal prompt.

    ``extra`` is retained only as a source-compatible deprecated argument.  It is
    deliberately ignored: arbitrary caller/env text must not become an invisible
    global model instruction.  Task-specific behavior belongs in the user request,
    a selected skill, tool schema, or an explicit operator-owned control surface.
    """
    del extra
    return _BASE_PROMPT
