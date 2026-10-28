---
method_id: page-authoritative-journal-before-guessed-keyword-recovery-2a28d46e6924
name: page-authoritative-journal-before-guessed-keyword-recovery
description: 上下文压缩或续接（如用户只说'继续'）后，若缺失的事实是自己上一轮的输出原文，先沿系统已暴露的确定性取回路径走：对 range 元数据 complete=false 且给出 next_start 的权威投影按句柄续页；若单条消息在投影中仍被预览截断，则用事件行内嵌的 session id 一次定向定位会话 journal 文件取全文。只有确认该输出从未被持久化时，才退回关键词/产物搜索。避免用猜出来的短语并行打 search_evidence/search_files、空命中后换词重试、超时后退化成全目录枚举。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:35effbfe-0312-45d2-a1bd-0418c1706ecd:91:09b2dff8eb8e9c779245
evidence_refs: learning:learn:2adcaf3b6a49
created_at: 2026-10-18T21:14:24.611749+08:00
updated_at: 2026-10-18T23:28:08.432090+08:00
---
## Trigger
续接/压缩恢复后，需要取回的是本会话自己上一轮的输出内容；同时存在一个恢复句柄或事件流投影，其 range 元数据明确 complete=false 且带 next_start，或每条 action_trace 行都内嵌 session id

## Discriminator
恢复投影的 range 元数据当时已声明 complete=false 且 next_start 存在（完整内容可确定性续页取回），恢复清单明示'优先 read_evidence 精确分页取回、不要重跑 source'，且每条事件行都带有 session=<id>——即权威原文已有确定性可达路径，不需要用臆测的关键词短语去做发现式搜索

## Short path
- 读恢复清单/事件流投影第一页；未知量：上一轮结论全文是否已在投影内？
- 若 complete=false 且 next_start 存在，按句柄续页或提高 limit、缩 scope=current_session；未知量：上一轮评估的完整原文
- 若投影对单条长消息仍只给预览截断，用事件行内嵌 session id 定向定位会话 journal 文件（一次定位，非全库内容搜索）；未知量：权威全文的落盘位置
- 从续页/journal 提取上一轮结论，与 git log/status 的当前代码状态对齐，再继续任务实施
- 原文与当前代码状态均已核实即停止恢复，进入执行

## Stop conditions
- 已从投影续页或 session journal 取回上一轮输出完整原文
- 投影 complete=true 且预览已含任务所需全部内容
- journal 中确认该输出从未持久化（此时才退回关键词/产物搜索）

## Verification
- 取回原文与事件流预览前缀逐字一致（同一 session/blob）
- 续作内容引用的上一轮结论能在 journal 中逐条对上
- 未为此重跑原 source，也未发起全库内容搜索

## Counterexamples
- 上一轮输出从未写入任何 journal（纯流式、无事件落盘）→ 分页/journal 路径不存在，关键词搜索产物与历史是正当手段
- 目标是某工具结果而非自己的回答，且已有精确 Evidence ref → 直接 read_evidence 该 ref，不翻整条事件流
- 投影 scope 与所需内容不同域（workspace vs current_session）→ 续页当前 session 不含目标，应显式换 scope 而不是叠加关键词
- 投影已 complete=true 且包含所需全文 → 直接使用并停止，不做任何恢复动作
