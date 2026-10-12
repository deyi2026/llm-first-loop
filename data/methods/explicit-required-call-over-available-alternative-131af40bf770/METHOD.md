---
method_id: explicit-required-call-over-available-alternative-131af40bf770
name: explicit-required-call-over-available-alternative
description: 当任务明确规定必须发出某个工具调用，即使该工具在下一轮 schema 中不可见，且明确禁止使用看似可用的替代工具时，应沿显式协议发出 required_tool；不要因工具隐藏而改调 forbidden_tool。先确认参数与协议一致，发出 required_tool，收到回执后停止并报告。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:9f0b8d02-5ee4-426e-bd9f-1eeca2436fb0:0:11626921cfec6642a958
evidence_refs: learning:learn:3ba9a7c10993
created_at: 2026-09-22T16:58:24.826051+00:00
updated_at: 2026-09-22T16:58:24.826051+00:00
---
## Trigger
任务要求下一轮必须发出指定工具调用，且该工具可能被隐藏；同时明确禁止调用当前可见的替代工具。

## Discriminator
协议中存在显式 required_tool/params 与 forbidden_tool 约束，且当前可见工具列表出现替代工具但任务未授权替代。

## Short path
- 确认协议要求的工具名、参数和禁止项
- 忽略可见替代工具的诱惑，发出 required_tool 调用
- 收到 required_tool 回执后停止工具调用
- 按协议输出完成标记或如实报告回执

## Stop conditions
- required_tool 回执已收到
- 协议要求的输出已生成
- 发现协议冲突或安全限制时停止并报告

## Verification
- 检查未调用 forbidden_tool
- 检查 required_tool 名称和参数与协议完全一致
- 检查最终输出只基于实际回执，不编造

## Counterexamples
- 协议明确允许在 required_tool 不可见时改用指定 fallback
- required_tool 调用违反安全或权限边界，应停止而非强行发出
- 任务只要求完成目标，未规定必须发出隐藏工具调用
