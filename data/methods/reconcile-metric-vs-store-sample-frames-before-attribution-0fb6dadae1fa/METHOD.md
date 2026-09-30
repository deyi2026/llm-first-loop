---
method_id: reconcile-metric-vs-store-sample-frames-before-attribution-0fb6dadae1fa
name: reconcile-metric-vs-store-sample-frames-before-attribution
description: 对校验器/质量指标（如诚实率、declaration_check）的违规样本做归因时，先对齐两个采样口径：指标报告的样本量 N 与按 kind 检索持久 store 得到的记录数 M。N≠M 即存在 frame mismatch：归因必须显式限定为覆盖率 M/N 并声明其余不可取、不外推；回执正文截断时，细分类只能基于可见字段并单独标注。若失败签名匹配某条历史修复的目标模式，按 kind+ID 直查该修复的执行状态链：executed 但 unverified/无 completion → 复现归因到“修复未验证落地”，无需宽搜“为什么还在”。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:8:325acc515a6f2805b017
evidence_refs: learning:learn:f5e9af7d3e7f
created_at: 2026-09-30T08:09:52.209725+08:00
updated_at: 2026-09-30T08:09:52.209725+08:00
---
## Trigger
需要对某个质量指标或校验器标记的违规/False 样本做归因分类，且指标口径（如 self_evaluate 的诚实率样本）与持久化记录 store（如 search_records 的 kind 结果）是两个不同来源。

## Discriminator
两个来源的样本量当时即可直接对比且不相等（本集：store 检索仅返回 7 条 vs 指标样本 39 条），且回执正文明显截断（以 ... 结尾）——说明可归因覆盖率仅 7/39、细分类只能基于可见摘要；同时最早一条回执已点名相关历史修复 ID（EVO-20260820-409f3f60），其落地状态可直接按 kind=evolution_exec 精确查询，无需先做宽搜索。

## Short path
- 按目标 kind 全量取回违规记录（如 declaration_check，limit 拉满），记录返回数 M 与字段截断情况；未知量：违规样本在 store 中的全集形态。
- 从指标回执/evidence 读出指标样本量 N，与 M 对比；不等则把归因显式限定为 M/N，声明其余不可取、不外推；未知量：两个口径是否同一池。
- 仅基于未截断的可见字段做真阳性/系统性误报分类（元评论、自我披露、跨轮引用等模式），截断样本标注“基于摘要”。
- 若失败签名与回执已点名的历史修复匹配，直接按 kind+ID 查其执行状态链（executing/executed/unverified/completion）；unverified → 归因到修复未验证落地，给核验/补完选项而非新开修复或继续宽搜。
- 写出带覆盖率边界与回执来源映射的归因结论后停止。

## Stop conditions
- 可取回样本已全部分类，覆盖率（如 7/39）与不外推声明已写明
- M=N：两来源实为同一池，可全量归因，无需限定边界
- 修复状态链已确认：complete → 缺陷另寻根因；unverified → 归因到未验证落地

## Verification
- 答案中每个统计断言都能映射到具体回执（记录条数、样本量、状态记录）
- 覆盖率边界与“不做外推”的限定显式出现在结论中
- 修复落地/未落地的结论引用执行状态原始记录（如 evolution_exec 的状态两条），而非转述或推测

## Counterexamples
- 两来源计数一致（store 7 条 = 指标样本 7 条）→ 直接全量归因，覆盖率限定是多余仪式
- 指标回执明确声明其样本就是该 store 的完整投影 → 不存在 frame mismatch，无需对齐步骤
- 任务只问“是否存在至少一例违规” → 单例即可回答，不做覆盖率对齐
- 修复状态显示已 verified/complete 但失败仍复现 → 不归因“未落地”，转入根因分析（修复不足 vs 新变量）
