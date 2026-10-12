---
title: DSH 工具插件接入 LFL 桥接：依赖 agent/session/UI 上下文的插件装配成功但执行必失败，接入前需三步评估
scenario: 评估 DSH 插件接入 LFL（dsh_plugin_bridge MCP 桥）时：先查插件 inject 依赖与 Config schema（lib/index.js 的 inject 数组 + z.object 配置），识别是否依赖 agent/session/UI/客户端连接等 DSH 运行时上下文；装配成功后必须实测调用（call_tool）验证执行，不能只验证注册与 schema
root_cause: DSH 工具插件（dsh-tool-todo/ask-user）强绑定 DSH agent 运行时上下文（owning agent session / active UI provider / event-sourced session log），LFL 经 dsh_plugin_bridge 的 stdio MCP 通道无此上下文——工具能注册但执行必失败
solution: "接入前检查三步：① inject 依赖列表（grep \"const inject\" 插件 lib/index.js）——仅依赖 tools 等基础服务的插件才可能可用；② Config schema 必填项——bridge 需支持配置透传（manifest 支持 {name, config}，已实现）；③ 装配后实测调用一次（McpConnection.call_tool），被 agent/session/UI 上下文拒绝的插件直接回滚清单（注册假工具=误导+token 噪音）。可用替代：todo→文件待办/schedule；ask-user→现有事件驱动交互+send_feishu_message"
evidence: "2026-08-20 实测：todo_write 调用返回 \"requires an owning agent session\"；ask_user_question 依赖 active UI provider（headless bridge 无）；两插件装配/注册/参数校验全通但执行被拒，已回滚（commit 状态见工作区）"
tags: [dsh插件, mcp桥接, agent上下文, 接入评估, fail-close]
source: {}
status: active
created_at: "2026-08-20T01:53:48.005982+08:00"
updated_at: "2026-08-20T01:53:48.005982+08:00"
---