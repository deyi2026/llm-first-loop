---
method_id: batch-triage-unmerged-branches-by-structural-partition-766a3a87953d
name: batch-triage-unmerged-branches-by-structural-partition
description: 被问『这批未并入 main 的分支里还有哪些有效工作要合并』时，不要逐条先读提交内容。第一未知量是分区：用一次批量循环取每条分支的 ahead/behind、patch-id 等价计数（git cherry）与树差量级，立刻把十几条缩到几条机械不等价的幸存者（多数是 patch 等价或落后数百提交的历史残留）。只对幸存者列提交主题，并在 main 上定点检索每主题的关键符号做语义覆盖核验——机械不等价不等于内容缺失，main 常已用另一实现覆盖。通常仅 1~2 条活跃线含真增量，对它们读 diff 后再下合并结论。
aliases: 一堆旧分支哪些还没合进主干, 未合并分支批量排查, 分支盘点先判等价再读内容, 旧分支还有没有没进 main 的活, 多条分支合并优先级判断
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:2897:7986c3b6de3b33b2c6ae
evidence_refs: learning:learn:46705386b447
created_at: 2026-10-29T00:01:28.455912+08:00
updated_at: 2026-10-29T00:01:28.455912+08:00
---
## Trigger
用户/任务要求盘点一批（约五条以上）未并入基准（main）的分支，判断其中哪些还含有未上线的有效工作、需要合并或收口；清单里分支命名可见地混杂归档线、备份线、历史 fix 线与活跃线

## Discriminator
『未并入 main』≠『含 main 没有的内容』：判别量不是提交正文，而是每条分支相对 main 的 ahead/behind 计数、merge-base 祖先关系、patch-id 等价计数与树差量级——这些用一条批量循环即可全部取得，无需先读任何提交内容就能把 N 条缩到少数

## Short path
- 对全部未并入分支跑一次批量循环：ahead/behind 计数、祖先判定、patch-id 等价计数、main...branch 树差量级；未知量：哪些分支含 main 没有的工作
- 按输出三分区：patch 等价已在 main／落后数百且仅领先个别提交（历史残留）／领先落后皆小且树差小（活跃线）
- 仅对机械不等价（not_in_main>0）的分支列出具体差异提交主题；未知量：这些提交各是什么语义
- 对每个差异主题在 main 树上定点检索其关键符号/机制；未知量：main 是否已用另一实现覆盖该语义
- 只对确认真增量的分支读提交 diff 与文件清单，输出合并或不合并的结论

## Stop conditions
- 全部分支均已归入 patch 等价／语义已被 main 覆盖／归档残留三类，且活跃线的净增量已读取并确认
- 机械等价信号被抽检证伪（squash-merge、rebase 上下文漂移导致 patch-id 大量假阴性）且无替代分区信号时，停止依赖分区，退回逐条内容审阅

## Verification
- 抽一到两条被判『等价或已覆盖』的分支，核对其差异提交主题在 main 上确有对应实现或等价 patch
- 最终『真增量』分支的文件级 diff 与 main 上的定点检索结果互证：main 缺的正是这些文件或机制，不多不少

## Counterexamples
- 分支数只有两三条、或全部是活跃分支：分区开销超过收益，直接读内容更快
- 仓库采用 squash-merge 合并：patch-id 等价信号系统性失效，须改用提交主题或文件重合度等信号
- 用户要的交付物本身就是每条分支的内容清单（盘点报告），全量枚举是目的而非弯路
- 机械不等价且 main 无同主题实现时，也不能凭『分支更新、更严』直接判定并入：行为正确性须按真实数据形状独立验证，等价信号与正确性是两个未知量
