---
method_id: preclassify-record-kind-and-embed-currency-check-61032dc7e9bc
name: preclassify-record-kind-and-embed-currency-check
description: 向带类型与校验契约的记忆载体（save_experience/record store）写入知识、约定或交接内容前，先按内容的验证出处选 record_kind：本回合有直接回执证明生效的正向经验→experience；源自 candidate 方法卡、纯阅读交接、未复用约定或教训→lesson 且 verification_state=unverified，正文必须预写一条可执行的当前性验证动作（如 grep -n <关键字> <路径> 应命中，或跑 <命令> 应得 <结果>）。被拒时把回执当契约机械修正，最多重试一次。核心是把'靠拒收回执逐次学习存储契约'前移为写前判定，避免用写失败当探针。
aliases: 这条该记成哪一类记忆, 没回执就按 unverified 存, 写教训前先想好怎么自证, record_kind 写前就定, 存经验还是存教训, 这条经验还没被证明
status: qualified
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:496:89d1d3f08cdb0bff200c
evidence_refs: learning:learn:20b624d0e72c
created_at: 2026-10-09T20:05:05.645934+08:00
updated_at: 2026-10-30T10:49:45.881428+08:00
---
## Trigger
即将把知识/约定/交接/教训写入带类型与校验契约的记忆载体（如 save_experience 的 record_kind），尤其当内容源自 status=candidate/未验证的方法卡、纯阅读型知识交接或尚未复用的工作约定时。

## Discriminator
写入那一刻内容的验证出处已经可见：来源文本明确标注 candidate/not_evaluated/'仅阅读不能记 applied'/task_benefit 未评估，且本回合无生效回执——按定义即未验证内容，应选 lesson 而非 experience；同时该类 lesson 须携带可执行的当前性验证行才能通过写入校验。

## Short path
- 写前判定验证出处：内容是否有本回合直接回执证明生效？来源是否明示 candidate/not_evaluated/仅阅读？
- 有生效回执→record_kind=experience；否则→lesson+verification_state=unverified。
- lesson 正文先写好一条可执行的当前性验证动作（grep -n <关键字> <真实路径> 应命中；或复现 <命令> 应得 <结果>），再提交。
- 一次提交；若被拒，只按回执声明的具体缺口机械修正，最多重试一次，不换措辞盲试。
- 写入成功后回读确认 record_kind/verification_state/验证行齐全，再向用户如实汇报保存位置与未验证状态。

## Stop conditions
- 首次写入即成功（record_kind 与验证状态匹配且验证行通过校验）。
- 判定内容属瞬态观察、无复用价值，放弃持久化。

## Verification
- 回读已存记录：record_kind、verification_state=unverified 与当前性验证行三者齐全。
- 验证行引用的路径/命令真实存在且语义相关（将来能真正检出内容过期），不是为过校验拼凑的占位符。

## Counterexamples
- 内容确由本回合直接回执证明生效（如修复 succeeded 且 action 回执在手）：discriminator 反转，experience 才是正确类型，不适用'默认 lesson'分支。
- 目标存储没有 record_kind 校验或不要求验证行：嵌入 grep 行不再是通行要求，只按该存储实际契约写，不为模板虚构命令。
- 内容是一次性中间产物或即将被本回合后续动作取代的草稿：整条方法不适用，不该入库。
