---
method_id: hydrate-in-receipt-ref-before-loss-or-policy-verdict-b393f0bd7087
name: hydrate-in-receipt-ref-before-loss-or-policy-verdict
description: 回执只投影了状态（如 halt_reason=action_receipt_status:rejected）而用户要的原因/细节缺失时，先看回执里是否残留指向全量持久化记录的 ref/URI/句柄，并 grep 装配层确认 hydrate 通道是否已接线；用一次最小 live 复现+水合取回真因，与生产者拒绝码位点交叉验证后，按『真丢失 / 已存未投影 / 可回取但模型可见 schema 未声明』三分法定性并给对应修复建议。不要先立『策略拒绝』『丢数据』假设再宽枚举模块。
aliases: 回执只有状态码怎么挖真因, ref 水合取完整记录, 先水合再断言丢数据, 拒绝原因去哪了, halted 回执查真因, 投影裁掉的字段上哪找
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:3868:602b97053d406883d24f
evidence_refs: learning:learn:9a96c7163243
created_at: 2026-10-29T10:16:04.530280+08:00
updated_at: 2026-10-29T10:16:04.530280+08:00
---
## Trigger
工具回执只透出不透明状态码而用户追问的细节（拒绝原因/错误详情/完整载荷）缺失，同时回执体内仍带有 ref/URI/句柄类字段（如 receipt_ref、evidence ref、artifact id）

## Discriminator
该 ref 是否指向已持久化的全量记录、装配层（factory/组装点）是否给它接了 hydrate 通道——对生产者模块与装配点各做一次作用域受限 grep 即可确认。这条当时已在手的事实能把『原因被丢/被策略吞/只是没投影』三种假设缩成一次可验证的水合取证

## Short path
- 在可疑回执里枚举所有 ref/URI/句柄字段；未知量：哪个指针通向全量记录
- grep 该 ref 的写入点与持久化 store；未知量：全量记录存了什么、在哪一层被裁掉（聚合只投影状态？紧凑投影不透原因？）
- 在装配层确认 store.hydrate 已接线；未知量：调用方现在能否回取
- 用最小 live 操作复现 halted 回执，把 ref 交给 hydrate 取回完整原因，并与生产者拒绝码位点逐字交叉验证
- 按三分法定性给修复：真丢失→改生产者补记录；已存未投影→投影层补字段（不动既有 halt_reason 词表）；可回取但不可发现→可发现性缺口，补模型可见 schema/描述

## Stop conditions
- hydrate 取回的原因能逐字对应生产者代码中的具体拒绝分支，因果链闭合即停，不再枚举同族其他模块
- 确认回执无任何 ref 字段且无持久化 store → 立即转生产者侧排查，停止寻找回取通道

## Verification
- 水合返回的 reasons 与拒绝码产生处（如 URL/主机校验函数）原文一致
- 全仓检索该 ref 类型是否出现在任何模型可见 schema/工具描述中，作为可发现性判定依据
- 复现用的临时标签页/资源事后清理，不触碰用户既有会话状态

## Counterexamples
- 回执不含任何 ref/句柄且没有 receipt store → 原因确实未持久化，应直接修生产者补记录，而非找水合通道
- 状态码已自解释（如 404 且回显完整 URL）→ 无需回取全量记录，直接作答
- ref 通道有 TTL/权限限制、过期后 hydrate 失败 → 不能把水合当可靠恢复路径，结论应转向投影层直接透出原因
