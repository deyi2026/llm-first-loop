---
method_id: reverse-check-classify-apply-failure-duplicate-vs-drift-374b9b1e87ac
name: reverse-check-classify-apply-failure-duplicate-vs-drift
description: git apply 前向失败（patch does not apply）时，动手诊断或修复前先跑一条 `git apply --check --reverse`：reverse 通过=补丁已完整应用，前向失败只是重复应用，零修复动作即可收口；reverse 也失败才是内容漂移/冲突，才值得进入 3-way 或重生成分支。特别注意：目标文件 mtime 晚于补丁生成时间不构成漂移证据——应用补丁本身就会刷新 mtime。本集最初把失败归因为『补丁按旧快照生成、文档已被更新』并先行告知用户，随后一条 reverse check 即证伪：真实类别是已应用。
aliases: git apply 打不上先查是不是已经打过了, 补丁重复应用怎么识别, patch does not apply 反向校验, git apply --check --reverse 判断已应用, 补丁打失败别急着当冲突处理, 重复打补丁 前向失败 归因
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:674:c39c4213dd2316ab7a57
evidence_refs: learning:learn:a1ed78167c10
created_at: 2026-10-31T16:04:53.441328+08:00
updated_at: 2026-10-31T16:04:53.441328+08:00
---
## Trigger
git apply（或幂等应用类命令）前向失败，回执为 patch failed / does not apply，正准备归因（快照过期、并发修改、冲突）或选择修复手段（重生成补丁、3-way、手工改 hunk）时

## Discriminator
一条 `git apply --check --reverse <patch>` 的退出码即失败类别：退出 0（可整体反向应用）→ 补丁内容已完整存在于目标文件，前向失败=重复应用；非 0 → 真漂移或部分应用。mtime 顺序（目标文件比补丁新）在此不可作为漂移判据，因为成功应用补丁本身就会更新目标 mtime——本集 docs mtime 15:53 > patch 15:34 恰是已应用的产物而非反证。

## Short path
- git apply 失败回执到达：先把未知量收敛为『重复应用 vs 内容漂移』二选一，不先对外宣布归因结论
- 跑一条 `git apply --check --reverse <patch>` 取得判别：OK→重复应用；fail→漂移或部分应用
- reverse OK 时用一个内容锚点确认：取补丁中一条标志性新增行 grep 目标文件，配合 `git diff --stat HEAD -- <file>` 的插入量与补丁 + 行数量级比对；一致即停止，报告『已应用、工作区无需改动、多余补丁副本可删』
- reverse 失败才进入漂移分支：提取 hunk 头、比对上下文，决定 `git apply -3` 或按当前文件重生成补丁
- 整体 reverse 失败但个别锚点命中 → 整补丁级结论不成立，按文件/按 hunk 降粒度重复 reverse-check，识别部分应用

## Stop conditions
- reverse check 退出码与至少一个内容锚点（特征行 grep 或 diff 插入量）相互一致 → 停止诊断，不重生成、不 3-way、不手工编辑 hunk
- 已向用户报告失败类别及对应处置（重复应用→无需动作；漂移→给出修复路径）

## Verification
- `git apply --check --reverse <patch>` 退出码为 0
- 补丁新增的标志性行/新章节标题在目标文件命中，且位置邻近补丁 hunk 头给出的行号
- `git diff --stat HEAD -- <目标文件>` 的插入行数与补丁新增行数量级一致（本集 +190 对应补丁各 hunk 的 + 行合计）

## Counterexamples
- reverse check 也失败且无任何锚点命中：真冲突/漂移，须走 3-way 或重生成，不得强行 --reverse apply 回滚
- 部分应用状态：整补丁 reverse 失败但部分 hunk 锚点命中，此时整补丁级『已应用/未应用』结论均不成立，必须按 hunk 粒度分别裁决
- 失败根因是 whitespace/换行/CRLF（错误样式偏 context mismatch）：--reverse 判别无效，应改用 --ignore-whitespace 类选项验证
- 目标文件不在 git 工作区（无 git 可用）：退化方案是逐 hunk 取上下文行 grep 比对，不能套用 reverse check
