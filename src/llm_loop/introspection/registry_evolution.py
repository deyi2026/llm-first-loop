"""演进类工具注册（T2，design §2.1.2-5.2）.

承载: submit_evolution / evolution_complete / generate_evolution_template
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_evolution import SUBMIT_EVOLUTION_TOOL_DEF
from llm_loop.introspection.tools_evolution_template import EVOLUTION_TEMPLATE_TOOL_DEF
from llm_loop.introspection.tools_exec_complete import EVOLUTION_COMPLETE_TOOL_DEF


def tool_defs() -> list[dict]:
    return [SUBMIT_EVOLUTION_TOOL_DEF, EVOLUTION_COMPLETE_TOOL_DEF, EVOLUTION_TEMPLATE_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "submit_evolution":
        from llm_loop.introspection.tools_evolution import run_submit_evolution

        return run_submit_evolution(
            host.ctx,
            host.audit,
            args,
            audit_dir=str(host.audit_dir) if host.audit_dir else None,
        )

    if name == "evolution_complete":
        from llm_loop.introspection.evolution_exec import EvolutionExecutor
        from llm_loop.introspection.tools_exec_complete import run_evolution_complete

        if host.ctx.evolution_store is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[演进建议不可用] 事实: 演进建议存储未装配。原因: EVOLVE_ENABLED=0。建议: 检查配置。",
                tool_call_id="",
                tool_name="evolution_complete",
            )
        executor = EvolutionExecutor(
            exec_level=int(getattr(host.ctx, "evolve_local_exec", 0) or 0),
            store=host.ctx.evolution_store,
            audit_dir=host.audit_dir,
        )
        return run_evolution_complete(host.ctx, executor, host.audit, args)

    if name == "generate_evolution_template":
        from llm_loop.introspection.tools_evolution_template import run_generate_evolution_template

        return run_generate_evolution_template(host.ctx, host.audit, args)

    return None
