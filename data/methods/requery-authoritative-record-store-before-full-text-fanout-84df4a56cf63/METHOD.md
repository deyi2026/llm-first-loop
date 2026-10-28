---
method_id: requery-authoritative-record-store-before-full-text-fanout-84df4a56cf63
name: requery-authoritative-record-store-before-full-text-fanout
description: 当某记录/提案已在结构化记录库（evolution/治理记录存储）命中但显示被截断，之后需要其全文时，不要切换到 docs/文件内容/命令层做跨库扫描。先对同一记录库用更窄 query/更高 limit 重查；若库仍只给摘要，则把文档实质拆为两类：设计约束（自撰时已在上下文，直接沿用）与代码锚点（无论全文如何都必须对当前代码重核，因行号/路径会漂移），对后者逐条重核、路径失效时用一次文件名搜索重定位。全文取证到此即完成——跨库扫描和 shell grep 是把已定位来源的问题重新丢回全域枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:88:bf5927df4a4c13cfb44c
evidence_refs: learning:learn:3227e3d08b35
created_at: 2026-10-16T13:50:51.983885+08:00
updated_at: 2026-10-16T13:50:51.983885+08:00
---
## Trigger
需要已批准提案/治理记录的完整全文以进入实现，而该记录此前已在结构化记录库命中（显示截断），或文档为本会话近期自撰、设计约束仍在上下文中

## Discriminator
记录库已返回过该记录的命中（权威来源已定位），且 search_files/文档库对其 ID 的 miss 回执进一步证明它不是工作区文件；同时实现真正需要的不是全文本身，而是设计约束（在上下文中）+代码锚点（必须对当前代码重核）。

## Short path
- 需要全文时先重查已命中的记录库：同 kind+更窄 query/更高 limit 取未截断记录
- 库仍只给摘要则停止取证：拆分文档实质——设计约束沿用上下文，代码锚点列为待核清单
- 逐锚点对当前代码重核：read_file 原路径；路径失效（文件被移动）时一次文件名/glob 搜索重定位，不做目录级宽枚举
- 锚点全部核实/重定位/证伪后直接进入实现；不再有跨库全文搜索或同目的 shell 命令

## Stop conditions
- 同一记录库重查已取得未截断全文，或上下文约束+全部锚点已对当前代码核实
- 记录库与文件库双双 miss 且文档非自撰时停止换措辞枚举，改为向用户求证

## Verification
- 实现范围与决策时持有的约束逐条对应；每个锚点漂移（如 lifecycle.py 移至 core/loop/）被显式重定位并记录，而非默认沿用旧行号
- 复盘确认没有为获取记录库已持有内容而残留的跨库扫描或超时命令

## Counterexamples
- 文档由他人较早撰写且约束不在当前上下文：只能沿记录库取全文或向用户求证，『凭上下文实现』分支不适用
- 目标内容本来就是仓库内文件（设计文档/receipts）：search_docs/search_files 即权威库，『不扫文件』分支不适用——关键是识别哪个库已证明权威，而非禁用某类工具
- 提案可能在批准后被并发修订：实施前必须以记录库当次重读为准，凭记忆实现会引用过时约束（此时应叠加终局前重读权威记录的做法）
