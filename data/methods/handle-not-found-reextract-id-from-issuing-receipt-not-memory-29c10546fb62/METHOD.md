---
method_id: handle-not-found-reextract-id-from-issuing-receipt-not-memory-29c10546fb62
name: handle-not-found-reextract-id-from-issuing-receipt-not-memory
description: 跨工具句柄/ID 链（spawn→result、create→get、submit→status）中，第一次收到 handle/id 不存在类错误时，第一步不是怀疑签发失败，也不是凭上下文拼一个『像的』串重试，而是回到签发该句柄的原始回执，从正文或 evidence/结构化字段里逐字复制 ID（含前缀）再调一次。回执正文不显示 ID 时，ID 常藏在 evidence 块里——正文看不见不等于没有。只有逐字核对后仍 not found，才切换到『资源已过期/被回收』或『签发本身失败』假设。
aliases: child_id 从回执 evidence 里复制, handle 不存在 先查签发回执, 别凭上下文拼 id, spawn 回执里找不到 child_id 怎么办, subagent_result 连续报句柄不存在, 猜的 id 查不到
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:888:14b8d6fdc463f2078f7f
evidence_refs: learning:learn:6f676fb55458
created_at: 2026-11-01T11:43:26.085653+08:00
updated_at: 2026-11-01T11:43:26.085653+08:00
---
## Trigger
批量 spawn/创建多个子资源后，需要用回执中的句柄去调用第二个工具（查结果/结算/取详情），且首次调用即报 handle 不存在；或签发回执正文看似不含 ID、只剩『凭印象』可用时。

## Discriminator
签发回执（含其 evidence/附件字段）是否已含该 ID 的字面值。handle-not-found 最常见根因是调用方 pattern-completion 拼错（缺前缀、位数不对），而非签发失败——这一判别在首次失败时即可用：签发动作当时没有报错，且回执在手。

## Short path
- 首次 not-found 后，重开签发回执，在正文与 evidence/结构化字段中定位 ID 字段，逐字符复制（连前缀）重试一次；
- 若回执全篇确无 ID：改走权威列表/状态工具枚举真实 ID，或重新签发；绝不按上下文样式拼造新串；
- 若逐字 ID 仍 not found：切换假设为生命周期问题（已结算/被回收/过期），查状态或重签发，不再重复同一串。

## Stop conditions
- 用逐字复制的 ID 成功命中并取得终态/所需数据；
- 或确认资源已不存在，已重新签发或向用户报告。

## Verification
- 重试所用 ID 能在签发回执原文中逐字符找到（含前缀、无增删）；
- 成功调用的返回与签发记录指向同一对象（同一 child/job/goal）。

## Counterexamples
- 回执与其 evidence 均无 ID 且无列表工具可枚举：此时应重新签发或升级，『逐字复制』无从谈起；
- 逐字正确的 ID 仍 not found：属资源生命周期/回收问题，继续校对拼写无意义；
- 用户在对话中显式贴出的 ID：同样权威，可直接使用，不必回溯回执。
