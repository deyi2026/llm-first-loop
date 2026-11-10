---
method_id: repeat-guard-on-mandated-pacing-ledger-discharge-not-loop-abandon-8fd192447377
name: repeat-guard-on-mandated-pacing-ledger-discharge-not-loop-abandon
description: 异步子代理/准入闸轮询中，run 级重复守卫在完全相同的 wait 配速调用上触发时，先区分协议性重复与探索性冗余：若权威回执（如 waiting_protocol 字段）明确要求以相同形状的 wait+status 循环取终态，守卫的『不要继续重复探索』不适用于该循环。正确响应是把已核事实+未决+下一步写入 task_state 账本履行记账要求，然后以完全相同形状继续循环：不微调参数绕守卫，也不提前终止轮询。
aliases: 轮询被 repeat_guard 拦下要不要停, 等待循环被提示不要重复探索, 配速等待第三次被守卫计数, 按 waiting_protocol 轮询遇重复守卫怎么处理, duplicate guard fires while polling async child
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ad7ea3f-6860-49a6-a20b-9c436e6da865:2:20d93f5362184053b854
evidence_refs: learning:learn:80193ff38588
created_at: 2026-11-10T09:14:44.244192+08:00
updated_at: 2026-11-10T09:14:44.244192+08:00
---
## Trigger
轮询异步审查/子代理终态期间，repeat_guard 在第 3 次完全相同的 wait/配速调用上触发，而该循环是先前成功回执中协议字段（waiting_protocol：wait 仅配速、status 是唯一完成信号）明确要求的。

## Discriminator
被重复的调用是配速/等待原语——其效果是消耗墙钟预算而非获取新信息；且回执链显示同一未知量仍在推进（status 每次返回 qualification=pending 且 remaining_seconds 逐次递减）。同时满足这两点即为协议性重复，守卫『重复探索』的前提不成立。

## Short path
- 守卫触发时先给被重复调用分类：是结果已核的事实查询，还是协议要求的配步原语？
- 事实查询冗余 → 停止该分支，账本记账后转向下一未知量。
- 协议性配步 → 写 task_state 账本（已核事实/进行中协议/下一步），履行守卫的记账诉求。
- 以完全相同形状继续循环（wait→status）：不微调参数（如 wait(119)）规避守卫，也不终止轮询。
- status 回执出现定性终态字段（如 qualification=PASS）即退出循环，不再稳定性复查。

## Stop conditions
- 权威 status 查询返回定性终态字段并绑定稳定身份（child_id/材料 SHA）→ 立即退出循环
- 预算字段（remaining_seconds/deadline）接近耗尽仍 pending → 停止等待并上报/升级
- 守卫触发在事实查询类调用上且其先前回执已回答当前未知量 → 停止该查询分支，不再原样重发

## Verification
- 每次继续迭代后 status 回执仍在推进（remaining_seconds 递减、状态字段变化），证明循环非空转
- 终态确实经由协议指定的唯一完成信号（status）取得，而非把 wait 的 wake_reason=elapsed 当完成
- 账本条目含已核事实+未决+下一步三要素，守卫记账诉求履行后才继续循环

## Counterexamples
- 守卫触发在被重复的 read/search 类调用上，且先前回执已回答当前未知量 → 真探索冗余，应停止并转向下一未知量，不得『记账后原样重发』
- 无任何协议字段要求该循环、且连续多次调用之间回执零变化 → 重复是纯浪费，应换策略（拉长间隔/换渠道/上报），记账续发只会空转
- 被重复调用是带外部副作用的写操作（提交/发布/扣配额）→ 守卫触发必须先做幂等与后果检查，绝不能记账后原样重发
