---
method_id: pace-async-review-waits-from-receipt-estimated-budget-8915f08e580a
name: pace-async-review-waits-from-receipt-estimated-budget
description: 异步审查/准入子代理的受理回执自带量化预算：review_budget.estimated_seconds、deadline_seconds、async_retry_max 与 waiting_protocol 的单次 wait 上限。等待时长因此在受理时即可计算：首次 wait 取 min(协议单次上限, estimated_seconds)，deadline 只作上界不作等待目标；每次到点后仅调 status(child_id) 取终态，pending 回执里的 remaining_seconds 用于校准下一轮；终态回执是唯一完成信号。不要按“这类审查很慢”的印象设固定长等待——本集 21,620 字符材料预计约 216 秒、两轮 60 秒轮询即 PASS，此前按 40 分钟等待已被用户纠正。
aliases: 审查到底要等多久, 等待审查别拍时长, 子审查轮询等多久查一次, 回执里的预计秒数怎么用, 用户嫌等待设太长
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:1060:4d65564fd3ef2c2e588b
evidence_refs: learning:learn:134dec735093
created_at: 2026-11-05T13:00:01.280281+08:00
updated_at: 2026-11-05T13:00:01.280281+08:00
---
## Trigger
为特权动作（如 git push）启动独立/准入审查子代理并收到受理回执，回执含 review_budget（estimated_seconds / deadline_seconds / async_retry_max / material_chars）及 waiting_protocol（单次 wait 上限、终态查询入口），需要安排等待节奏时。

## Discriminator
受理回执在等待开始前就打印了预计耗时与死线（estimated_seconds、deadline_seconds），且 waiting_protocol 明确 status(child_id) 是唯一终态信号、wake_reason=elapsed 只表示计时到点——等待时长是回执中已存在的可读数字，不是需要按最坏情况去猜的未知量；缺 estimated 字段时可按 material_chars 粗估（本集观测约 0.01 秒/字符，仅作兜底）。

## Short path
- 审查受理后先读 review_budget 与 waiting_protocol：估计耗时、死线、重试上限、单次 wait 上限、终态查询入口。
- 首次 wait = min(协议单次上限, estimated_seconds)；不设超过 estimated 的首等，更不设数倍于 deadline 的固定长等待。
- 每次 wait 到点后只做一件事：用受理回执的同一 child_id 查 status 取终态；wake_reason=elapsed 本身不是完成信号。
- pending 回执的 remaining_seconds/attempts 用于校准下一轮等待长度；deadline 耗尽仍 pending 则按 async_retry_max 或回执升级路径处理，不无限轮询。
- 拿到 PASS 后按已获准的受保护动作以裸单命令执行（配合 bare-single-command 方法）。

## Stop conditions
- status 回执出现终态（PASS 或明确拒绝）即停止等待，进入执行或上报分支。
- remaining_seconds 归零且 attempts 达 async_retry_max 仍 pending → 停止轮询，按回执的升级/失败路径处理。

## Verification
- 实际出终态用时与 estimated_seconds 同量级（本集约 2 分钟出 PASS）；显著超过 deadline_seconds 才怀疑审查流程本身异常。
- 每次状态查询复用受理回执的同一 child_id，且终态回执的 candidate_sha256 与发起时一致，防止串到其他审查。

## Counterexamples
- 回执不含 review_budget/ETA 字段（普通异步任务、无预算子代理）→ 不得套数字配速，改用任务书或协议默认短轮询。
- 材料极大、estimated_seconds 本身就达数十分钟 → 首等偏长是回执推导的结果；规则是“按回执数字”而非“永远短等”。
- 同步阻塞式审查（无 child_id、无需轮询）→ 不适用。
