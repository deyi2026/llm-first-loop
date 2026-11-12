---
method_id: zero-delta-pending-poll-fold-to-ledger-wait-by-estimate-b8274da11af8
name: zero-delta-pending-poll-fold-to-ledger-wait-by-estimate
description: 异步闸（review_admission 类 status）轮询中，回执除剩余预算秒数递减外零增量、或 repeat_guard 提示同一精确调用已多次成功时，该次轮询本身已无信息量：先把已核事实（pending 次数、child_id、SHA 回显、预算态）折叠进 task_state 账本，再改用由 start 回执 estimated_seconds 推导的大间隔有界等待；终态到达核 SHA 回显即停，验收字段缺失则披露而非重查。
aliases: 轮询一直pending还要继续刷吗, 状态查询返回一模一样怎么办, 被repeat_guard提醒重复调用, 等异步审查结果多久查一次, pending轮询先记账再等, 按预估时长定轮询间隔
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc99ff08-658c-4355-afd2-b4b2ecc29011:0:af846dcec89df2e5ef39
evidence_refs: learning:learn:4b1756ef4e46
created_at: 2026-11-12T12:57:54.798408+08:00
updated_at: 2026-11-12T12:57:54.798408+08:00
---
## Trigger
异步准入/审查闸已受理，start 回执内嵌 waiting_protocol 与 estimated_seconds/deadline；status 轮询连续返回同型 pending（仅 remaining_seconds 递减、attempts 不变、无新增字段），或 repeat_guard 提示同一精确调用已第 N 次成功

## Discriminator
零增量回执本身即判别信号：pending 回执没有任何新字段说明这次查询未解决任何未知量，此时已核事实只有『pending 第 N 次确认 + 预算剩余』；而 start 回执当时已给出 estimated_seconds，足以推导合理等待量级，密集短轮询不缩小任何范围

## Short path
- 由 start 回执的 estimated_seconds 推等待量级，用 status 自带 wait_seconds 或单次长 wait 覆盖大部分预估时长，而非反复短轮询
- 首次出现同型零增量回执或 repeat_guard 提示：先把已核事实（child_id、candidate_sha256 回显、pending 次数、预算）写入持久账本（已核/未决/下一步），再继续等待
- 普通 wait 返回后（wake_reason=elapsed 只代表计时到点）立即查 status 核真实资格，不连续只等墙钟
- 终态到达：核 candidate_sha256 与 start 回显一致、scope/paths 与授权清单一致即停
- 用户验收点名字段不在终态回执 schema 内：不重发同参数查询、不伪造数值，如实披露缺失并交用户裁决

## Stop conditions
- 终态 qualification 返回且 candidate_sha256 与 start 回显一致
- 该已核 pending 事实已入账本且无新未知量时，不再重复同参数查询
- 回执出现新增字段（attempts>0、模型切换、错误、部分结论）时退出本分支立即响应

## Verification
- start 与终态两次回执的 candidate_sha256/child_id/scope 一致
- 同一精确调用不再出现第 3 次以上零增量重复（repeat_guard 不再触发）
- 账本条目含已核事实/未决/下一步三段并引用回执来源

## Counterexamples
- 回执含新字段（attempts>0、fallback、部分结论、错误码）是新信息，应立即处理而非记账后继续等
- 任务书以『等待参数+次数上限』定义轮询预算的 subagent_result 型工具，按 bounded-blocking-polls 计数重发，不适用本卡
- 终态回执本身打印了验收字段（如显式 P0/P1 计数）时直接判读，无需披露缺失分支
- 预估时长缺失、deadline 极紧或要求中途频繁汇报进度的闸，按 estimate 推大间隔等待不成立
