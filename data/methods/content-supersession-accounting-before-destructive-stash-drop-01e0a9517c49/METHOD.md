---
method_id: content-supersession-accounting-before-destructive-stash-drop-01e0a9517c49
name: content-supersession-accounting-before-destructive-stash-drop
description: 清理工作区或 drop stash 前，先对待销毁副本逐文件做内容超集核算：改动是否已按提交落地（log 指纹）、内容是否被当前树完全超越（行数/watermark/哈希量化比较）。存在副本独有内容时先恢复再销毁；恢复时 stderr 的 gitignore 提示只约束 git add，是否入库以 git status 的 M/?? 为准，M 文件照常提交保持树净。避免『直接 drop 丢真实数据』与『误判不入库漏提交』两类返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:621:f6652341c77962edd454
evidence_refs: learning:learn:0295ec1b709c
created_at: 2026-10-16T00:20:12.848689+08:00
updated_at: 2026-10-16T00:20:12.848689+08:00
---
## Trigger
需要销毁性清理（drop stash / checkout -- 还原脏文件），且待销毁副本混合代码改动与数据文件、运行时账本等，无法仅凭提交记录确认内容已全部被当前树超越

## Discriminator
逐文件量化比较：stash 版数据 22 行/watermark 22 > 当前树 20 行 ⇒ 存在副本独有内容，禁止直接 drop；代码改动出现在已落地提交指纹中 ⇒ 可销毁。恢复时 gitignore 警告文本只针对 git add（『Use -f if you really want to add』），tracked 与否以 git status 的 M/?? 为真值，不由 ignore 提示推断

## Short path
- 读提交账（log 指纹）确认哪些副本文件改动已落地
- 对待销毁副本逐文件量化比对当前树（行数/计数/watermark/哈希），标出仅存于副本的唯一内容
- 唯一内容：从 stash checkout 恢复 → git status 看 M/?? 决定是否提交（M 则提交保持树净；?? 且在 ignore 目录则不入库）
- 确认无副本独有内容后 drop 该 stash，drop 后复核 stash 列表与树脏数
- 树 0 脏 + 目标 stash 处置完毕即停，不扩展到范围外的其他 stash

## Stop conditions
- 待销毁副本与当前树逐文件比对后无任何独有内容，或独有内容已恢复并按 M/?? 处置入库
- git status 干净（或仅剩有意保留项）且 stash 列表只减少目标条目

## Verification
- drop 前：副本中计数/哈希大于当前树的部分已有去处（工作区或提交）
- drop 后：stash 列表核对，恢复的数据行数与 stash 记录一致（如 20→22 行）且提交包含该数据
- 范围外 stash（如标注 preserve 的变体）未被触碰

## Counterexamples
- 副本内容全部是已按指纹落地的代码改动且无数据文件 → 比对后直接 drop，无需恢复/提交步骤
- 副本数据是可再生成的测试产物（reports 类自生成文件）→ checkout -- 还原即可，不做入库
- 恢复后 git status 显示 ??（真 untracked，ignore 目录）→ 确实不入库，保留工作区即可，勿 git add -f 破坏 ignore 约定
- stash 明确标注为待集成的保留变体 → 不属于本次清理范围
