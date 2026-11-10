---
method_id: stop-at-first-terminal-receipt-no-stability-repoll-a87cc6bda898
name: stop-at-first-terminal-receipt-no-stability-repoll
description: 轮询契约（如 waiting_protocol）已声明 status 是唯一正式完成信号、且回执已返回定性终态字段（qualification=PASS/REVISE）并绑定稳定身份（child_id/材料 SHA）时，该首次终态回执即闭合轮询：不存在『终态稳定性』这个待验证未知量，资格签发后不漂移（漂移由 use-time 复核负责）。此时再次原样重复同一查询属于 post-sufficiency 动作，会被 repeat_guard 判冗余；正确下一跳是把已核事实记入账本并直接产出报告，缺失字段如实披露。
aliases: 拿到PASS还要不要再查一遍, 终态回执要不要复查稳定性, 审查通过后重复轮询是冗余吗, 第一次读到终态就停, PASS了别再poll
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6722b8e9-fba5-4dbc-8edf-5181a7bc2cc3:0:205e40fe3a449eaad604
evidence_refs: learning:learn:71a1db1f38fb
created_at: 2026-11-10T08:21:34.040509+08:00
updated_at: 2026-11-10T08:21:34.040509+08:00
---
## Trigger
异步子代理/审查回执契约明确某查询通道为唯一完成信号，且该通道刚返回含明确终态字段的回执；执行者犹豫是否再调一次同一查询『确认终态稳定』。

## Discriminator
回执是否已含定性终态字段（如 qualification=PASS）且无 pending/provisional 标记；资格是否绑定到不随重读变化的稳定身份（child_id、candidate SHA）。二者同时成立即表明『稳定性』是自造未知量——契约文本本身已写明该通道是完成信号，绑定型签发不会因再次读取而改变。

## Short path
- 按契约配速（wait≤120s 夹一次 status）轮询，直到回执出现终态字段
- 首次读到终态即视为轮询闭合：核对 child_id 与 start 回执一致、candidate SHA 与受审版本一致
- 不再重复同一查询；立即把已核事实（child_id、终态、SHA、缺失字段清单）写入 task_state 账本并引用回执
- 直接产出最终报告，回执未回显的必报字段按缺失如实说明，不编造
- 若后续真要使用该资格，依赖契约定义的 use-time 复核，而非现在再 poll

## Stop conditions
- 终态回执已核对身份一致（child_id/SHA），已记入账本并完成报告
- 回执出现 REVISE/失败类终态 → 按任务书 STOP 分支处理，同样无需再确认

## Verification
- 回执含明确 qualification 终态值，不是 pending
- start 与 status 回执的 child_id、candidate_sha256 逐字一致
- 契约文本（waiting_protocol 或等价字段）确认该查询通道为唯一完成信号
- 无任何字段把该结果标注为初步/可撤销窗口内

## Counterexamples
- 回执仍是 pending 或缺少终态字段 → 继续按契约轮询，本方法不适用
- 任务书明确要求『连续两次读到同一终态才算确认』→ 用户契约优先，照做
- 回执语义标注为 provisional 或在撤销窗口内可变 → 复核有真实依据
- 查询非幂等、或读取本身改变状态 → 重复调用有副作用，另议
