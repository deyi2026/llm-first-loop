---
method_id: patch-identity-merge-audit-not-ancestry-or-topic-7368b47013a4
name: patch-identity-merge-audit-not-ancestry-or-topic
description: 审计『本批分支是否都进了 main/集成分支』时，不要用分支祖先(--no-merged)或主题关键词判定落地：squash/rebase 工作流会留下假未合并分支，主题 grep 会撞相似历史。先由 main tip 与分支提交消息判定落地方式，再用 patch 级比对(git cherry/patch-id)量化未落地补丁，对幸存者直接测文件/补丁同一性，并以处置记录区分『等价已并/有意暂缓/卡闸无人收口』，归零后才执行审查、合并与重启。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:1020:ae82523b7aa256071738
evidence_refs: learning:learn:5b45d7a26277
created_at: 2026-10-17T13:18:34.622340+08:00
updated_at: 2026-10-17T13:18:34.622340+08:00
---
## Trigger
用户要求核查今天/本批多个分支是否都已并入 main（或集成分支）、或判断某修复是否已落地，并以此决定审查/合并/重启等收口动作；仓库并行分支多、且历史可能经 rebase/squash 改写。

## Discriminator
知识时点即适用的判别：main 单日 ahead 数十提交、分支 tip 等于/落后 main 且分支消息与 main 近期提交同文 ⇒ rebase/squash 落地，--no-merged 必然超报（本例 11 个候选中 9 个假阳性）；内容比对后幸存补丁携带全新文件（如新测试文件）⇒『该文件是否存在于目标树』是二元判别，强于主题关键词（关键词曾误中 37 个无关匹配）。

## Short path
- 按日期后缀/命名约定圈定本批候选分支，读 main tip、今日提交量；工作区未提交改动先记录不动
- 判定落地方式：历史无 merge commit 而分支消息与 main 近期 squash 提交对应 ⇒ 以 patch 级比对(git cherry/patch-id)为主仪器，--no-merged 仅作粗筛
- 对粗筛幸存分支逐个内容比对，得到量化清单：N 个补丁未按内容进 main（本例 11→2，且两分支携带同一补丁）
- 对幸存补丁直接测同一性：目标树是否含其新增文件（二元判别）；多分支变体只需 diff 补丁确认仅 rebase 偏移；不用主题关键词 grep 判定落地
- 查处置记录（docs/规则/回执）：有暂缓记录→报告不代收；无记录且存在合并闸规则→按闸收口（独立审查+全量门禁）后 ff 入 main
- 补丁清单归零后再 publish+重启，终态以服务权威记录核对 desired commit/generation；他人 WIP 留原样

## Stop conditions
- 未落地补丁清单为空（全部内容等价落地）→ 直接进入审核/重启段
- 幸存分支有明确暂缓/放弃处置记录 → 不代为收口，报告即可
- 未提交改动/运行中进程经 cwd 与会话记录归属为其他活跃会话 → 不清理不合并，重启走发布线而非工作区
- 用户未授权合并或重启 → 止步于核查报告

## Verification
- 抽查 --no-merged 与内容比对的差集 1-2 个分支，确认其补丁确以等价形式在 main（patch-id 命中）
- 幸存补丁的新增文件在目标树确实缺失（git log --all -- <file> / ls-tree）
- 收口并重启完成后，服务 status 的 desired commit/generation 与合并后 main tip 一致

## Counterexamples
- 仓库真实使用 merge commit 并线：--no-merged 即真值，patch 级比对是多余开销
- 手头只有主题描述、无分支或补丁引用（『我们修过 X 吗』）：关键词检索是唯一抓手，主题搜索反而合理
- 单一会话独占仓库、无并行 WIP：归属排查与发布线/工作区区分可省略
