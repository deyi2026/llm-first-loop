"""Playwright E2E 工具注册（T2，design §2.1.2-5.2）.

承载: playwright_test
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult
from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.tools_playwright import PLAYWRIGHT_TEST_TOOL_DEF


def tool_defs() -> list[dict]:
    return [PLAYWRIGHT_TEST_TOOL_DEF]


def execute(name: str, args: dict, host: RegistryHost) -> ToolResult | None:
    if name == "playwright_test":
        from llm_loop.introspection.tools_playwright import run_playwright_test

        return run_playwright_test(host.ctx, host.audit, args)
    return None
