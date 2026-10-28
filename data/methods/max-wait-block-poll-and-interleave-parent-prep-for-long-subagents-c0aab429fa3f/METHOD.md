---
method_id: max-wait-block-poll-and-interleave-parent-prep-for-long-subagents-c0aab429fa3f
name: max-wait-block-poll-and-interleave-parent-prep-for-long-subagents
description: 派遣长任务子代理后，不要对终态查询工具做零等待自旋轮询。spawn 回执已文档化 wait 参数区间并明示『可继续父级工作』，且派遣任务书本身就预测 child 会运行很久。把『连续 N 次完全相同的未结算回执』换成『少数几次贴近上限的阻塞等待 + 等待窗口内完成父侧既定准备工作（建目录、定唯一文件名、固化基线）』。终态到达后先检查截断，再经 evidence_ref 分段恢复全文并核验 blob SHA 与 complete=true 才落盘。
aliases: 子代理跑太久别空转轮询, 阻塞等一下顺便干自己的活, evidence_ref 分段取回全文, 等终态先查有没有截断, 跑太久别盯着轮询, 等的时候先备物料
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25393690-39c2-43d8-b50f-3157a58aaea2:38:ae7103898051d07dc0a6
evidence_refs: learning:learn:49a69db88647
created_at: 2026-10-15T01:20:40.598854+08:00
updated_at: 2026-10-23T05:52:04.065335+08:00
---
## Trigger
spawn 出预计长时间运行的子代理（多文件/多 hunk/多文档核验类任务），父会话必须等待其结算，且父侧存在完成后必做的确定性准备工作

## Discriminator
spawn 回执自身已写明 subagent_result(wait_seconds=0..30) 并明示『可继续父级工作、可 steer』；同时派遣任务书枚举的重任务面（六文件/逐 hunk/多必读文档/hash 核验）在第一次轮询前即可预测：快速连续查询只会返回逐字节相同的『尚未结算』回执，零信息增量

## Short path
- 派遣时即由任务面估计 child 预期时长，把首次 subagent_result 查询的 wait 设为回执文档化区间的上端
- 若一次最大等待后仍在运行，在两次查询之间执行父侧临界路径上的确定性准备（mkdir 回执目录、列既有文件定唯一文件名、记录待保护基线），而非空转再查
- 收到 completed 终态后先检查回答是否被截断；若截断，用回执内 evidence_ref 按大 limit 分段恢复原文直到 complete=true，并核对 blob SHA 一致
- 全文在手且完整性核验通过后才落盘回执，并复核被审面/基线未被扰动

## Stop conditions
- child 已达终态且完整原文已恢复并核验（complete=true 且完整性锚一致）
- 轮询回执开始携带增量进度信息（状态/轮数/工具数变化）——此时继续查询本身有信息量

## Verification
- 统计连续 subagent_result 回执：出现 ≥3 次逐字节相同且无新字段，即判定为零等待自旋，应提高 wait 或插入父侧工作
- 确认所用 wait 达到回执文档化区间上端；确认父侧准备项在 child 结算前已利用等待窗口完成
- 确认落盘内容与 child 终态原文一致（完整性锚匹配），而非截断版或父侧总结替代

## Counterexamples
- child 任务很轻（预计秒级完成）：一次短等待查询即可，最大等待反而无谓阻塞父会话
- 父会话需要中途 agent_message 纠偏或响应用户打断：长阻塞等待降低响应性，短间隔查询或事件通知更合适
- 查询工具没有可控 wait 参数：自旋轮询是唯一等待机制，本方法不适用
- 每次轮询回执都携带新进度信息：频繁查询有信息量，不属于冗余调用
