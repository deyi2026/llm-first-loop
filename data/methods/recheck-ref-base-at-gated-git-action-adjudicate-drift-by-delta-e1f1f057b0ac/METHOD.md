---
method_id: recheck-ref-base-at-gated-git-action-adjudicate-drift-by-delta-e1f1f057b0ac
name: recheck-ref-base-at-gated-git-action-adjudicate-drift-by-delta
description: 交接/任务书给出的前置 git 事实（目标 ref 停在哪、领先多少、可 ff）只在复验时刻为真；仓库存在外部写者时，到真正执行受门禁的状态变更（如 ff-only 合并、publish）那一刻，必须窄读一次目标 ref 当前值。发现漂移不要盲干也不要整体停：先查 reflog 定位外部写者与时间，再重算 base..branch 增量裁决——增量恰为本会话新提交、终态与原授权一致且结构约束（ff-only）仍成立，则继续执行，但把漂移单独写进回执与报告；增量含外来提交、终态改变或时序授权被打破则停下上报。非门控事实的漂移（如 untracked 数量变化且交集仍空）只记录，不触发重裁决。
aliases: main被外部推进了还能继续合并吗, 交接快照过期还能用吗, 合并前发现base变了, 别人先合了我的分支怎么办, ff窗口还在但ref动了
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:0:18632cfdd75d8d4a87ef
evidence_refs: learning:learn:62cccd89b09f
created_at: 2026-10-28T16:41:37.525524+08:00
updated_at: 2026-10-28T16:41:37.525524+08:00
---
## Trigger
即将执行受授权/门禁约束的仓库状态变更（ff-only 合并、publish 等）；任务书的前置事实（目标 ref 值、领先提交数、ff 可行性）是本会话早前时点复验过的快照；且仓库存在其他写者（外部会话/worktree 可推进同一 ref），快照与动作之间隔了一段工作时间。

## Discriminator
动作时刻重读目标 ref 与早前复验值比对；不一致时，reflog 的外部推进记录（谁、何时）加重算的 base..branch 增量构成裁决事实：增量==本会话新增提交且合并终态不变→漂移不改变授权结果；增量含外来提交、ff 破裂或终态改变→授权前提已被打破。增量重算在发现漂移之前不可得，但漂移本身只需一次窄读即可暴露。

## Short path
- 接手时按任务书一次性复验快照事实（ref 值、clean 状态、交集），此后修门禁项、跑全量期间不重复复验 ref
- 到达改状态动作那一刻，先窄读目标 ref 当前值与 base..branch 增量（一次 rev-parse/rev-list 即可，不重扫全部事实）
- 无漂移→直接执行既定动作
- 有漂移→查 reflog 定位外部写者与时间，重算增量，逐条对照硬约束：结构约束（是否仍可 ff-only）、终态（目标 tip 是否不变）、时序约束（如"修完才许合并"是否被外部打破）
- 结构与终态一致→继续执行，把漂移事实写进合并/发布回执，并在最终报告单独成段；否则按约束停下上报
- 被外部打破的时序约束必须显式报告（被谁、何时打破），不因"合并结果一样"而静默吸收

## Stop conditions
- 动作时刻 ref 无漂移且其余门禁绿→执行并核验终态
- 漂移但增量==本会话新增提交、终态一致、ff 仍成立→执行并显式记录偏差
- 增量含外来提交、ff 不成立或终态改变→停止，按 NOT_FF 类约束上报，绝不 rebase/强推凑合

## Verification
- 动作完成后 rev-parse 目标 ref == 预期 tip
- reflog/时间戳证据留存，偏差在最终报告单独成段
- 时序授权被外部打破的事实出现在回执与报告中，未被吞掉；未验的核验项（如部署三要素）明确标注未验

## Counterexamples
- 单写者仓库或执行窗口内 reflog 无任何外部写者记录：逐动作重验是纯开销，接手时一次复验即可支撑全程
- 漂移只发生在非门控事实上（如 untracked 数量 10→13、且与待合并文件交集仍空）：记录差异后继续，不触发整套重裁决
- 外部以 rebase/cherry-pick 换 SHA 方式合入：按 SHA 计算的增量会误判为"外来提交"，须改按关键文件的 scoped 内容 diff 裁决
- 漂移使合并终态包含未经本会话审查的外来提交：即使 ff 结构上仍成立，也必须停下上报，不能因"结构可行"继续
