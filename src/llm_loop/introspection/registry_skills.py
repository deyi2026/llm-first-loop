"""Codex 风格 Skills 工具注册（T2，design §2.1.2-5.2）.

承载: code_review / grill_me / stop_slop / handoff_now / brainstorm_design /
      tdd_red_green / design_review / record_skill
执行委托至 tools_skills / tools_handoff / tools_superpowers / tools_record_skill。
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_handoff import HANDOFF_TOOL_DEF
from llm_loop.introspection.tools_record_skill import RECORD_SKILL_TOOL_DEF
from llm_loop.introspection.tools_skills import (
    CODE_REVIEW_TOOL_DEF,
    GRILL_ME_TOOL_DEF,
    STOP_SLOP_TOOL_DEF,
)
from llm_loop.introspection.tools_superpowers import (
    BRAINSTORM_DESIGN_TOOL_DEF,
    DESIGN_REVIEW_TOOL_DEF,
    TDD_RED_GREEN_TOOL_DEF,
)


def tool_defs() -> list[dict]:
    return [
        CODE_REVIEW_TOOL_DEF,
        GRILL_ME_TOOL_DEF,
        STOP_SLOP_TOOL_DEF,
        HANDOFF_TOOL_DEF,
        BRAINSTORM_DESIGN_TOOL_DEF,
        TDD_RED_GREEN_TOOL_DEF,
        DESIGN_REVIEW_TOOL_DEF,
        RECORD_SKILL_TOOL_DEF,
    ]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "code_review":
        from llm_loop.introspection.tools_skills import run_code_review

        return run_code_review(host.ctx, host.audit, args)
    if name == "grill_me":
        from llm_loop.introspection.tools_skills import run_grill_me

        return run_grill_me(host.ctx, host.audit, args)
    if name == "stop_slop":
        from llm_loop.introspection.tools_skills import run_stop_slop

        return run_stop_slop(host.ctx, host.audit, args)
    if name == "handoff_now":
        from llm_loop.introspection.tools_handoff import run_handoff_now

        return run_handoff_now(host.ctx, host.audit, args)
    if name == "brainstorm_design":
        from llm_loop.introspection.tools_superpowers import run_brainstorm_design

        return run_brainstorm_design(host.ctx, host.audit, args)
    if name == "tdd_red_green":
        from llm_loop.introspection.tools_superpowers import run_tdd_red_green

        return run_tdd_red_green(host.ctx, host.audit, args)
    if name == "design_review":
        from llm_loop.introspection.tools_superpowers import run_design_review

        return run_design_review(host.ctx, host.audit, args)
    if name == "record_skill":
        from llm_loop.introspection.tools_record_skill import run_record_skill

        return run_record_skill(host.ctx, host.audit, args)
    return None
