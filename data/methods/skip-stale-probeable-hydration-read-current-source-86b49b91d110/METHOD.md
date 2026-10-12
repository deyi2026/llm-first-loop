---
method_id: skip-stale-probeable-hydration-read-current-source-86b49b91d110
name: skip-stale-probeable-hydration-read-current-source
description: 恢复中断执行、重建『已做到哪一步』时，从 evidence 索引挑选水合目标前，先用行内 freshness/version_policy 标注预判可读性：标注 stale 且 version_policy=probeable 的条目会被读取策略（probeable_source_stale）确定性拒绝，不要发起历史水合；优先水合 snapshot_only 的命令/观察快照，一次取得退出码、测试通过数等硬事实；需要 diff/当前内容时直接读权威源（git diff、当前文件），需要历史内容本身时才显式 allow_stale。本集该预判可省去一次注定失败的 hydration，且后续审查正是用 git diff 替代了那条历史 diff evidence。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ca02bdc1-1ca9-4389-9732-e3ba796f5550:392:6a14b39ceccb8abe276a
evidence_refs: learning:learn:ff5e4e069c63
created_at: 2026-10-07T17:43:19.585341+08:00
updated_at: 2026-10-07T17:43:19.585341+08:00
---
## Trigger
恢复中断执行或重建历史执行状态时，手握 evidence 索引回执（每条 ref 附 freshness/version_policy 标注），需要选择水合哪些 evidence 以确认此前动作结果。

## Discriminator
索引行内已明示 freshness=stale 且 version_policy=probeable ⇒ 历史读取将被 probeable_source_stale 策略拒绝（本集 edit_file diff 条目）；freshness=unknown 且 version_policy=snapshot_only 的命令输出快照可直接水合成功（本集 execute_command 条目）。两组标注都出现在水合动作之前的同一回执中，满足 knowledge-at-time。

## Short path
- search/list 拿到最近 evidence refs 及行内 freshness/version_policy 标注
- 只对非 stale 的 snapshot_only 观察快照发起 hydration，一次取得退出码/测试结果等硬事实
- 对 stale+probeable 的 diff 条目跳过历史水合：要当前内容 ⇒ 直接 git diff 或读当前文件；要当时内容 ⇒ 显式 allow_stale=true 请求
- 快照事实 + 当前源 delta 足以重建执行状态后即停止水合，转入与任务书硬性条款的 gap 对照

## Stop conditions
- 已从可水合快照取得确认执行状态所需事实（退出码、通过数等）
- 剩余未知量只能由当前源回答 ⇒ 转向 git diff / 读当前文件，不再追历史 evidence
- 需要的是历史 diff 本身 ⇒ 走显式 allow_stale 读取，此路径不视为摩擦

## Verification
- 反事实重放：去掉该次 stale hydration 调用，状态恢复结论（574 passed、工作区改动清单）不变 ⇒ 该调用为无信息跳
- 策略回执核对：被拒原因 probeable_source_stale 与水合前索引行内标注完全一致 ⇒ 拒绝可预先判定，无新信息产生
- 程序化检查：hydration 前断言行内 freshness!=stale 或 version_policy==snapshot_only，否则走 refresh/当前源分支

## Counterexamples
- 审计/归因场景需要证明『某时刻文件内容』作为证据：此时 allow_stale=true 的历史读取是正确动作，跳过 stale 条目反而错误
- 索引回执未标注 freshness/version_policy ⇒ 无先验可判，尝试性水合并读回执是合理探索，不适用本方法
- 需要最新内容但权威源不可直接访问（无 git/文件读取通道）⇒ 只能走 evidence refresh 流程，本方法不覆盖
