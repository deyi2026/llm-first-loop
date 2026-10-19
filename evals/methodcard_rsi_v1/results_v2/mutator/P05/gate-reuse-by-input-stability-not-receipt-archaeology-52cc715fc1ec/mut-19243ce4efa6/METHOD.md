---
method_id: gate-reuse-by-input-stability-not-receipt-archaeology-52cc715fc1ec
name: gate-reuse-by-input-stability-not-receipt-archaeology
description: 跨会话续跑后要判断一次已执行过的昂贵准入门（全量测试门）是否覆盖当前待交付产物时，若回执指纹无法对账（文档记录的 candidate SHA 与己方记忆不一致、当前会话 evidence 库为空），不要枚举各回执存放处考古；改做输入稳定性覆盖论证：被回退的再生成噪声自带门运行时间戳，配合交付集 index==worktree 与文件 mtime 早于门时刻，即证明『门输入树==当前树』，exit=0 可迁移、无需重跑。仅当规则强制要求本次动作持精确 SHA 的有效 PASS 回执时才需要回执——那就直接新申请准入，而不是找回旧回执。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:1208:c26c1bb4f4b5f0aab456
evidence_refs: learning:learn:22bd0b7f1974
created_at: 2026-10-16T11:05:22.340508+08:00
updated_at: 2026-10-16T11:05:22.340508+08:00
---
## Trigger
跨会话/续跑场景：需决定一次已执行过的昂贵准入门（全量测试、构建门）是否覆盖当前待交付产物，但其回执指纹跨会话无法对账（文档记录与己方记忆的 candidate SHA 不一致、当前会话 evidence 库为空、receipts 目录无当日回执）

## Discriminator
摩擦点之前已在手的两条事实即可闭合判断：①被当作噪声回退的再生成产物（测试报告 JSON）自带 2026-10-16T09:31 重跑时间戳＝门运行时刻的直接证据；②git status 已显示交付集全部 staged 且 index==worktree（无未暂存改动）。此时只需一条 mtime 列表命令：交付文件全部早于门运行时刻 ⇒ 门输入树==当前树，exit=0 可迁移——与任何文档记录的回执 SHA 无关（SHA 不一致本身对『是否重跑』是红鲱鱼）。

## Short path
- git status 确认交付集 index==worktree、无半成品；staged 集合即待判覆盖对象
- 对 unstaged 再生成噪声 diff：若仅时间戳/boilerplate 变化，其内嵌时间戳即门运行时刻证据；回退以保持准入面干净
- 单命令列出交付文件 mtime 与门运行时刻比较：全部 ≤ 门时刻 ⇒ 覆盖成立，不重跑门、不再枚举回执存放处（evidence/receipts/自报告/stash）追查 SHA
- 对下一个受门动作（如 push）重新申请准入；执行时按回执绑定的精确命令单独执行，不做复合命令（复合会使命令指纹失配被闸阻断）
- 重读权威记录（fetch + 远端 tip / ahead 计数）确认同步，披露范围外工件（并行施工线 untracked 文件）后收口

## Stop conditions
- 交付集任一文件 mtime 晚于门运行时刻，或出现 index≠worktree 的未暂存改动 ⇒ 覆盖断裂，立即改走重跑门分支
- 再生成 diff 含语义变化（非纯时间戳）⇒ 不是噪声，先查明再谈覆盖
- 规则要求本次动作本身持有效 PASS 回执（精确 SHA）⇒ 稳定性论证不能替代回执，直接新申请准入
- 覆盖成立 + 新动作准入 PASS + 权威记录复核一致 ⇒ 停止取证，进入执行/收口

- Verification 未逐条通过前不结案（覆盖全部 1 条验证条目）

## Verification
- 回退噪声前后各一次 git status：确认仅时间戳类噪声被回退、交付集字节不变
- mtime 列表逐文件 ≤ 门运行时间戳（门时刻取自再生成产物内嵌时间）
- 推送后 fetch + rev-list 计数：ahead=0 且远端 tip==本地提交

## Counterexamples
- 门跑在另一 worktree / 远端 CI 上：本地文件 mtime 与该输入树无关，不可据此复用结论
- 门本身廉价（秒级单测/静态检查）：直接重跑比稳定性取证链更短更稳
- 工作树无再生成副产物可佐证门运行时刻：缺时间戳证据时只能重跑门或重新取证
- 单一权威回执可当场重读并对账：直接对账即可，无需绕道稳定性论证
