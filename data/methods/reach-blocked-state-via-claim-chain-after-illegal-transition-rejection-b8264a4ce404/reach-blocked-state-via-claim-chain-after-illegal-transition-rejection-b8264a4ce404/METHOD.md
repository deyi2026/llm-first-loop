---
method_id: reach-blocked-state-via-claim-chain-after-illegal-transition-rejection-b8264a4ce404
name: reach-blocked-state-via-claim-chain-after-illegal-transition-rejection
description: 把 durable 任务记到非默认状态（如等待外部平台放行的 blocked）时收到转移级拒绝（『非法转移: pending → blocked』），该回执本身就是状态机 spec：它点名当前状态与非法边，合法到达链几乎总是 claim→in_progress→目标态；且这类 store 对 pending 任务的首写会隐式 claim（回执明示 pending→in_progress 由程序代签）。正确动作是两段写：首写借隐式 claim 进 in_progress 并取 claim token，第二写携带平台侧事实作 reason 落到 blocked，回执确认即停止，不换状态名硬试。字段级预检错误（缺必填字段、类型不匹配）不属于本方法，按字段差分单次重签处理。
aliases: 任务置为阻塞态被系统拒绝, 先认领再改任务状态, 状态流转报错后的正确顺序, 等平台放行的任务先挂起登记, 改任务卡状态一直报错
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:d24ffc8b-f80b-4443-ad45-b1f71ccff1a7:483:9793560487e6ce332873
evidence_refs: learning:learn:87c17378a5ae
created_at: 2026-11-20T09:26:45.037794+08:00
updated_at: 2026-11-20T09:26:45.037794+08:00
---
## Trigger
需要把任务 store 中 pending 状态的任务记为等待外部放行的非默认状态（如 blocked），状态写被拒且回执是转移级错误（非法转移：当前态→目标态），而非字段级预检错误。

## Discriminator
拒绝回执已暴露两个当时可用的事实：(1) 当前状态是 pending 且到目标态没有直接边；(2) 同一会话先前的成功回执已证明该 store 对 pending 任务首写会隐式 claim（pending→in_progress 由程序代签、发 claim token）。两者合起来直接锁定合法链 pending→in_progress→blocked，不需要枚举其他状态写法或字段组合。

## Short path
- 未知量=如何把任务记为等待态：按本会话已成功回执的调用形态发状态写（必填字段齐全、evidence 传 string 不传 list）
- 遇『非法转移: pending→blocked』：把该回执当状态机 spec，锁定合法链 claim→in_progress→目标态，不改状态名重复硬发
- 首写借 store 隐式 claim 进 in_progress，从回执取 claim token
- 第二写 in_progress→blocked，reason 放可核平台事实（受理 id、受理时间、公网实测结果）
- 回执确认 blocked 与 reason 落盘即停止，不再对同一状态写做变体重试

## Stop conditions
- 回执显示任务已到目标态且 reason 含可核事实，状态簿记完成
- 试探表明 store 不存在到达该状态的合法链：改用 notes/description 字段承载等待语义，不继续枚举状态值

## Verification
- 最终回执状态字段等于目标态（→ blocked），reason 含平台侧可核事实（受理 id、时间、实测不可见）
- 无对同一非法转移的同形重复调用（重复即未把拒绝当 spec）

## Counterexamples
- 字段级预检失败（缺 title、evidence 期望 string 传了 list）→ 属于『拒绝原因即合同差分』的单次字段修正重签，不需要走状态链
- 目标转移本就合法直达（如 pending→done）→ 一次写完，不要插入多余 claim 步骤
- 想写入 store 未定义的状态值（如 waiting_platform）→ 任何转移链都到不了，应改用 reason/备注承载语义，而非枚举状态名
- 失败来自瞬时故障或网络超时 → 按重试语义原样重发，不走转移链
