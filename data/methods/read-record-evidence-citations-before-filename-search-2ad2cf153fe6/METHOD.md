---
method_id: read-record-evidence-citations-before-filename-search-2ad2cf153fe6
name: read-record-evidence-citations-before-filename-search
description: 当待核对的实现事实已被手头记录的 evidence/引用字段指到具体文件、行号，或可由记录 ref 直接导出路径时，先沿这些 provenance edge 精确读取，再做任何文件名枚举。宽枚举会命中 venv/eval runtime/worktree 下大量同名副本（本集 store.py 命中 20 个跨环境路径），把'读一个已知文件'变成'先消歧再读'。仅当引用缺失、存在性探测失败、或任务本身要求清点全部副本时才升级为宽发现。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:138:78cf216493a800c1bd1a
evidence_refs: learning:learn:bcdd387b3082
created_at: 2026-09-19T04:35:49.569351+00:00
updated_at: 2026-09-19T04:35:49.569351+00:00
---
## Trigger
下一步需要实现级事实（状态机行为、参数面、提案原文条款），且已检索到的记录中存在指向这些事实的 evidence 引用（路径:行号、数据文件路径）或可由 ref 导出的文件路径。

## Discriminator
发起文件名搜索前，lesson 记录（已在手）的 evidence 字段已明确列出权威路径：src/llm_loop/methods/store.py、data/audit/evolution_suggestions.jsonl、introspection 各文件行号；且 experience:EXPERIENCE-20260919-diff 可直接导出 experiences/EXPERIENCE-20260919-diff.md。这些引用当时已足以把'哪个文件回答状态机/原文'从全库候选缩到 1-2 个精确读取，但模型仍先做了 store.py 文件名搜索（20 个跨环境命中）、*record-use* 搜索（无匹配）和 experiences 目录枚举。

## Short path
- 一次定向 search_records 取回 v1/v2/lesson 的 refs（未知量：确切引用标识）。
- 读记录正文与 evidence 字段，机械提取已引用的实现路径:行号与数据文件路径。
- 逐条按引用精确读取（store.py 状态机、EVO jsonl 原文、v2 正文），每次读取绑定一个明确未知量。
- 只对记录中确实未给出的路径（data/methods 存储目录）做一次窄 find。
- 依坐实事实执行修订（存 v3→退役 v1/v2→重写 lesson 归因），再以 search_records 验证发现面收敛 + 文件回读 round-trip。

## Stop conditions
- 引用来源已回答当前未知量（状态机行为、提案原文归属坐实）即停止发现、转入编辑。
- 修订完成后，检索验证发现面只剩新版且回读与写入一致，即停止。

## Verification
- 发起任何文件名/glob 搜索前，先核对所需标识符是否已出现在早前回执或记录 evidence 字段；有引用仍先枚举即判违规。
- 实际读取的路径须与记录 evidence 引用逐字一致，避免串到 venv/eval runtime/worktree 下的同名副本。
- 此类任务的宽枚举调用次数应为 0（本集 search_files×3 属可省路径）。

## Counterexamples
- 引用路径不存在或仓库已重构（记录陈旧）：先做一次存在性探测，探测失败后才退回宽发现，不盲信旧引用。
- 任务目标是清点全部副本/变体（审计重复文件、seed vs runtime 盘点）：枚举本身即任务目标，本方法不适用。
- 手头记录无任何 evidence 引用且 ref 无法导出路径：此时宽文件发现才是正确起点，本方法不禁止它。
