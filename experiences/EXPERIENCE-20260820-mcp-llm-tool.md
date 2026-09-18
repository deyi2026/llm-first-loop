---
title: MCP/自定义工具注册两大致命约束：LLM 工具名协议合法 + Tool 协议公开字段完整
scenario: "MCP 插件或自定义工具接入后，服务重启/工具首次真实注册时出现：① registry.schemas() 遍历报 AttributeError: 'McpTool' object has no attribute 'description'；② LLM API 400 拒绝 tools schema（Invalid 'tools[N].function.name'，含点号/非法字符）。"
root_cause: 基线单测从未覆盖注册表遍历/LLM 侧 schema 提交路径：McpTool 只存 self._description 违反自声明 Tool 协议；工具名点号直接透传违反 OpenAI 兼容工具名约束。MCP 首次真实注册时才同时暴露（修复第一个后第二个立刻显现）。
solution: "① 注册名统一经 _registry_name() 协议化：原始 mcp.<server>.<tool> → mcp_<server>_<tool>（正则 [^a-zA-Z0-9_-] 替换为下划线），满足提供方约束 ^[a-zA-Z0-9_-]+$；底层 MCP 调用仍用原始 tool 名（_mcp_name），只改 LLM 侧注册名。② Tool 子类必须完整实现注册表协议公开字段 name/description/parameters/execute——description 用 @property 公开内部 _description（dataclass frozen 也兼容）。③ 改名必须同步所有前缀匹配点（热刷新 unregister 前缀、日志/返回名、测试断言），否则热刷新失配。验证路径：注册→registry.schemas()→LLM 真实调用全链路单测 + 重启后端到端实测。"
evidence: commit ddd8b16（2026-08-20）；重启后端到端聊天实测通过；63 个相关单测全绿
tags: [mcp, 工具注册, 协议约束, 潜伏bug, llm-api]
source: {}
status: active
created_at: "2026-08-20T01:35:50.189138+08:00"
updated_at: "2026-08-20T01:35:50.189138+08:00"
---