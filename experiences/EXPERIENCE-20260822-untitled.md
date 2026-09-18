---
title: 本地模型工具轮零历史注入导致失忆循环（只读查询停滞）——根因与修复
scenario: 本地大模型（qwen3.8-27b）执行简单健康检查任务卡住近 2 小时，日志显示反复只读查询停滞循环：architecture_status/execute_command/read_file/search_archive/search_records 交替重复，模型每轮看不到自己已收集的信息。需判断是否与程序注入有关并修复。
root_cause: "2026-08-21 为缓存命中新增程序注入 TOOL_ROUND_ZERO_HISTORY=1（工具轮零历史：只发 system+摘要+最近结果，effective_budget 被 min 压到 4000 字符，engine.py _tool_round_zero 分支）。本地模型工具轮因此看不到自己上轮已执行的工具与结果（动作轨迹不可见），表现为'每轮失忆'→ 反复重查同一批只读工具。日志实证：会话 03:15→05:01 共 114 次工具调用全部为只读查询，末尾 10+ 轮 architecture_status/execute_command 交替停滞。这违反用户四原则④'避免程序错误影响大模型发挥'——缓存前缀稳定性优化以牺牲模型对自身动作的可见性为代价。"
solution: ①取消零历史注入：.env TOOL_ROUND_ZERO_HISTORY=1 → 0（原子写入已校验），工具轮回到带最近消息（LMS_CHAT_TAIL=16 提供最近 16 条，TOOL_ROUND_BUDGET=8000 小前缀路径），模型能看见自己已做的动作轨迹，规则③'重复动作/无进展即调整或回答'自然触发收敛；②重启 web/feishu 服务使 .env 生效；③规则层无需新增复杂引导——可见性恢复后现有停滞调整规则即可生效；④修复方向=减少程序约束（程序简单直接，让 AI 自主判断），而非增加程序控制。
evidence: "data/event_logs/d1192d8c-7906-4cee-9b43-7645a68c0d45.jsonl 首条 03:15:52 末条 05:01:44；工具调用序列 114 次全为只读查询、末尾 architecture_status/execute_command 交替 >10 次；engine.py:485-490 _tool_round_zero 分支 min(effective_budget,4000)；build.py:51/70 零历史注释；.env:172 修改前 TOOL_ROUND_ZERO_HISTORY=1。"
tags: [本地模型, 程序注入, 停滞循环, 工具轮, 缓存优化, LLM失忆, 健康检查]
source: {}
status: archived
created_at: "2026-08-22T13:03:24.423223+08:00"
updated_at: "2026-09-06T00:15:07.572782+08:00"
---

## 2026-09-06 lifecycle review

该记录根因/修法依赖 TOOL_ROUND_ZERO_HISTORY=1 的旧工具轮零历史机制；当前 source/config 已无该机制，故作为已修复历史事故归档。
