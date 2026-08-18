"""cache_guard: 缓存命中规则校验（MCP 唯一出入口——请求总闸）.

方案（2026-08-18 用户指派实现）:
- 所有 LLM 请求经 prompt-guard 校验（5 类规则）后放行——前缀稳定工程保证
- MCP server 注册 validate_request tool（协议就绪——可独立进程）
- 稳定后可内化 engine（规则引擎函数化——MCP 层可撤）
"""

from llm_loop.cache_guard.guard import GuardDecision, validate_request, PromptGuard

__all__ = ["GuardDecision", "validate_request", "PromptGuard"]
