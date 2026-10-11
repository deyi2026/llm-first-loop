---
method_id: hydrate-terminal-closure-evidence-before-recovery-search-32bde0e15581
name: hydrate-terminal-closure-evidence-before-recovery-search
description: 跨会话极简续跑（如“按建议执行”）且无活动 goal 时，证据索引回执本身就是恢复地图：上一会话最后时刻落盘的 closure 类 evidence（save_experience、present_files，时间戳最新）是点名式 recovery handle，直接 hydrate 即拿到权威 experience_ref 与交付物路径，无需对 docs/evidence 库做任何关键词搜索。仅当终端边失效或证实无关时，才转用其它已点名 provenance（miss 回执文档清单/续跑备忘/git delta）。与 resume-continuation 卡的判别器差异：本卡在搜索之前、以索引终端条目为判别器；该卡在首次 miss 之后、以回执点名文档/备忘/git 为判别器。本集中 3 次换措辞搜索全 miss，而索引前两条已给出答案入口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:125:09d4d3cd5e6946a04495
evidence_refs: learning:learn:752a11b11789
created_at: 2026-10-12T01:07:55.466047+08:00
updated_at: 2026-10-12T01:07:55.466047+08:00
---
## Trigger
极简续跑指令（如“按建议执行/继续”）且无活动 goal，当前是新会话而目标工作属于上一会话；此时已拿到（或可立即拿到）一份证据索引回执（list_evidence 类）。

## Discriminator
在任何关键词搜索之前，索引回执已显示上一会话的终端 closure 条目：acquired_at 最新、source 类为 save_experience 与 present_files（本集均为 23:59:06，会话最后两条 acquisitions）。hydrate 它们即可点名 experience_ref 与交付物路径（回执 role=recovery_handle），无需搜索。

## Short path
- 读 status + 证据索引各一次；按最新时间戳和 closure 类 source（save_experience/present_files）识别上一会话的终端条目。
- 直接 hydrate 这两条；解决的未知量：上一会话的结论与“建议”记录在哪。
- 沿被点名 refs 前进：读交付物文档全文，并按精确 experience_ref 检索经验记录（search_records）；解决的未知量：结论清单与修订要求。
- 沿文档自身的 provenance（其头部点名的对应设计文档与章节）补齐剩余原文；截断时用 evidence hydration 的 range 分页而非重读整文件。
- git branch/log 一次确认工作区状态；随后按恢复出的建议逐线执行，每线以回执为凭收口。

## Stop conditions
- 执行所需的全部事实都已带 provenance 回执重读（终端条目 + 其点名的下游记录），恢复阶段结束、开始执行。
- hydrate 后发现终端条目与任务无关或缺失：切换到备选已点名 provenance（miss 回执文档清单/续跑备忘/git delta），而不是对同一库再换措辞搜索。

## Verification
- 每条恢复出的结论都能溯源到 hydration/read 回执（blob hash、acquired_at），而非记忆或搜索摘要。
- 被点名的 experience_ref 与交付物路径在据以制定计划前真实可解析（search_records 命中/读取成功）。
- 交付物摘要行与经验记录对结论的表述一致，才允许写出派生产物（如 v2 修订）。

## Counterexamples
- 指令本身已点名产物（如“按 docs/x.md 的建议执行”）→ 直接读该文件，不做索引恢复流程。
- 索引终端条目是任务中途的常规观测（如某 execute_command 输出）而非 closure 产物 → hydrate 它得不到状态地图；应改用 resume-continuation 卡的三条边（miss 回执点名文档/续跑备忘/git delta）。
- 同会话续跑（上下文仍温）→ 直接继续，恢复仪式纯属浪费。
- search_docs 首次 miss 回执列出的文档确实与任务相关 → 直接沿这些引用走更便宜，该情形由既有 resume-continuation 卡覆盖，不必启用本卡。
