"""cache_guard MCP server——LLM 请求唯一出入口（协议层）.

MCP tool: validate_request（请求元数据 → 放行/拦截/警告 + 审计）.
独立进程（stdio）或进程内接入（FastMCP 同进程运行——当前默认进程内直调 PromptGuard，
协议层就绪——稳定后可独立进程部署——MCP 出入口语义不变）。

运行（独立进程时）:
    python -m llm_loop.cache_guard.mcp_server
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_mcp_server(audit_file: str | None = None):
    """构建 MCP server（FastMCP——validate_request tool）."""
    from mcp.server.fastmcp import FastMCP

    from llm_loop.cache_guard.guard import PromptGuard

    mcp = FastMCP("prompt-guard")
    guard = PromptGuard(audit_file=audit_file)

    @mcp.tool()
    def validate_request(
        session_id: str,
        system_text: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        run_round: int | None = None,
        compress_count_this_run: int = 0,
    ) -> dict:
        """LLM 请求前校验（唯一出入口）：5 类规则（system 稳定/注入纪律/工具结果/窗口漂移/隐私）.

        Returns: {verdict: ALLOW|BLOCK|WARN, rule, detail}——调用方按 fail-open 处理.
        """
        d = guard.check(
            session_id=session_id,
            system_text=system_text,
            messages=messages,
            tools=tools,
            run_round=run_round,
            compress_count_this_run=compress_count_this_run,
        )
        return {"verdict": d.verdict, "rule": d.rule, "detail": d.detail}

    return mcp


def main() -> None:
    """独立进程运行（stdio 传输）."""
    logging.basicConfig(level=logging.INFO)
    mcp = build_mcp_server()
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
