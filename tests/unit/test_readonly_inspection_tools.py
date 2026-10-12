"""Narrow read-only inspection access without general shell authorization."""

from __future__ import annotations

import threading

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.registry import ToolRegistry
from llm_loop.tools.safety import is_readonly_command


@pytest.mark.parametrize(
    "command",
    [
        "rg -n 'card-lifecycle' docs",
        "rg --files docs/promotion/receipts",
        "rg -n 'method|experience' src --glob '*.py' | head -n 12",
        "rg -l 'workspace_base' src",
        "grep -n 'rm -rf | chmod | kill' docs/ai_rules.md",
        "git show --stat HEAD",
        "git --no-pager show --format=oneline HEAD",
        "git grep 'card-lifecycle' -- docs",
        "git ls-files docs",
        "git ls-files '*.md'",
    ],
)
def test_safe_inspection_queries_remain_callable_in_readonly_mode(command):
    reg = ToolRegistry(exec_mode="readonly")
    assert is_readonly_command(command), command
    assert reg._check_exec_mode("execute_command", {"command": command}) == ""


@pytest.mark.parametrize(
    "command",
    [
        "rg -n pattern; touch unapproved",
        "rg -n pattern && mkdir scratch",
        "rg pattern | tee output.txt",
        "rg pattern > out.txt",
        "rg pattern | python -c 'print(1)'",
        "rg --pre=python pattern .",
        "rg --pre python -n pattern .",
        "rg --pre-glob=*.md pattern .",
        "rg pattern $(echo extra)",
        "rg pattern \x60echo extra\x60",
        "rg pattern\nuname",
        "git show HEAD --output=output.txt",
        "git show -ooutput.txt HEAD",
        "git show HEAD --ext-diff",
        "git show HEAD --textconv",
        "git grep --open-files-in-pager='sh' pattern",
        "git grep -O pager pattern",
        "git -c core.pager='sh' show",
        "git show HEAD; echo chained",
        "grep marker | xargs touch",
    ],
)
def test_inspection_queries_do_not_gain_shell_or_write_capabilities(command):
    reg = ToolRegistry(exec_mode="readonly")
    assert not is_readonly_command(command), command
    assert "仅放行只读命令" in reg._check_exec_mode(
        "execute_command", {"command": command}
    )


def test_other_exec_mode_protections_remain_unchanged():
    readonly = ToolRegistry(exec_mode="readonly")
    assert "禁止写文件" in readonly._check_exec_mode(
        "write_file", {"path": "docs/report.md"}
    )
    blocked = ToolRegistry(exec_mode="blocked")
    assert blocked._check_exec_mode(
        "execute_command", {"command": "rg -n term ."}
    )
    allowlist = ToolRegistry(exec_mode="allowlist", exec_allowlist="echo")
    assert allowlist._check_exec_mode(
        "execute_command", {"command": "rg -n term ."}
    )


class _ObserveTool:
    """In-memory concurrent observer; intentionally no file/network side effect."""

    description = "read-only observer"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str, barrier: threading.Barrier, seen: list[tuple[str, str]]):
        self.name = name
        self.barrier = barrier
        self.seen = seen

    def execute(self, **kwargs):
        self.seen.append((self.name, current_session_id.get()))
        self.barrier.wait(timeout=3)
        return self.name


def test_search_files_joins_readonly_parallel_pool_with_session_context():
    barrier = threading.Barrier(2)
    seen: list[tuple[str, str]] = []
    registry = ToolRegistry()
    registry.register(_ObserveTool("search_files", barrier, seen))
    registry.register(_ObserveTool("read_file", barrier, seen))
    token = current_session_id.set("parent-session-for-child-review")
    try:
        results = registry.execute_many([
            ToolCall(id="s", name="search_files", arguments={}),
            ToolCall(id="r", name="read_file", arguments={}),
        ])
    finally:
        current_session_id.reset(token)
    assert [result.tool_call_id for result in results] == ["s", "r"]
    assert all(result.status == ToolResultStatus.SUCCESS for result in results)
    assert set(seen) == {
        ("search_files", "parent-session-for-child-review"),
        ("read_file", "parent-session-for-child-review"),
    }
