---
method_id: index-versioned-report-chain-before-adhoc-evidence-reads-0988210ce2a1
name: index-versioned-report-chain-before-adhoc-evidence-reads
description: 在版本化实验报告语料（DESIGN/PLAN/AUDIT/RESULT 同族命名、以 hash/状态互相交叉引用的多里程碑链）上撰写或核验带具体数字的综述/文章/评审时：先用一次族级索引（grep -rln 族关键词，或读 execution-plan/triage 类文档）拿到全部里程碑及其资格状态，再只读支撑目标论断的冻结文档，边写边把每个数字登记到具体文档+版本。避免逐份 ad-hoc 读结果文档、读到中途才发现文档族结构与权威版本，也避免把不同版本（v0.1/v0.2）的数字混引。
status: candidate
source_model: workbuddy/step-5-preview
source_episode_refs: episode:1c391008-9819-4e88-92ce-117820e41b2e:35:551c88e0a495f9e9c0d2
evidence_refs: learning:learn:741fc17645bc
created_at: 2026-10-18T19:12:33.574770+08:00
updated_at: 2026-10-18T19:12:33.574770+08:00
---
## Trigger
需要基于一个含多版本、多里程碑实验文档的仓库产出或核验带具体数字与结论的综合交付物（文章、评审、总结），且同主题存在多个 RESULT/AUDIT 版本并存、资格状态互不相同

## Discriminator
读到的第一份结果文档本身已暴露这是链式语料：标题带里程碑版本号、状态行含前序版本与后续里程碑（如 DEFERRED）、正文引用 design authority 与 baseline hash；这意味着一次 grep -rln 族关键词即可枚举全族，且 plan/triage 类文档自带逐里程碑状态表，可当权威链索引用，无需逐份试读才发现结构

## Short path
- 读第一份文档时确认里程碑链与命名族存在；未知量：全族有哪些文档、哪些是最终冻结的权威结果
- 立即做一次族级枚举（grep -rln 族关键词）并定位 plan/triage 索引文档；未知量：每个里程碑的资格状态与对应权威文档是哪几份
- 按索引只读将支撑目标论断的冻结文档，边读边把每个数字登记到具体文档+章节+版本；未知量：每条论断的可回溯来源
- 同一数据集内结果混合时（如效率指标全绿但 Hard Gate FAIL），依据索引中的状态字段把正反两面证据都纳入交付结构，不做单向选取
- 全部保留论断均可回溯到具体文档后停止；无法回溯的表述删除或补证

## Stop conditions
- 每个保留的数字/结论都映射到具体文档、章节与版本号
- 族级枚举已确认没有遗漏资格状态不同的更新版本（避免引用已被 v0.2 取代的 v0.1 数字）
- 混合结果的正反两面证据均已进入交付物

## Verification
- 把版本敏感数字（跨版本对比、百分比、通过率、失败分类计数）逐条对回被引文档原文行
- 用族级枚举结果复核被引文档确为该里程碑的最新冻结版
- 抽查交付物中每个结论是否都能给出『文档名+章节』级来源，无来源即不合格

## Counterexamples
- 任务只涉及单份文档或文档间无族结构、无交叉引用时，直接读目标文档即可，索引步骤纯属浪费
- 用户只要某一份指定文档的内容，不需要全景，不应先做族级枚举
- 语料无命名规范且无 plan/index 类文档时，宽发现本身就是必要前置步骤，本方法不适用
- 需要原创分析而非引用既有结论的任务：权威性取决于推理而非文档链，索引收益有限
