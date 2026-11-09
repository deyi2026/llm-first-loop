---
method_id: reanchor-post-compaction-completion-claims-via-authoritative-receipts-f6a77672ff6c
name: reanchor-post-compaction-completion-claims-via-authoritative-receipts
description: 长会话经 compaction/恢复后，上一条完成汇报里的载荷断言（已推送、已发布、资格已消费）在当前上下文往往没有工具回执支撑。用户问"结果出来了吗"时，不要凭恢复的记忆直接确认：把每条断言映射到唯一权威面（远端 git、release 资产表、child 终态 status），各发一次只读核验；语义匹配预期的错误回执（如 not_owned=资格已被消费）本身就是核验通过的证据。全部断言有当前回执后才回答，并逐字引用 commit/SHA。
aliases: 压缩恢复后的汇报还能信吗, 无回执的完成声明先核实再答, 答用户结果前先对账回执, 恢复后别凭记忆确认完成, 错误回执当核验证据用
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:3492:979352c30a3e61cbac5a
evidence_refs: learning:learn:f618b7c1ce5a
created_at: 2026-11-08T23:05:28.834635+08:00
updated_at: 2026-11-08T23:05:28.834635+08:00
---
## Trigger
用户询问此前已汇报的完成/结果是否属实，而该汇报生成于 compaction/上下文恢复之后，其关键声明在当前会话缺少工具回执支撑

## Discriminator
汇报在场≠回执在场：逐条检查载荷断言是否有本会话可见回执；每条外部状态断言都存在唯一权威面（远端 ref、release 注册表、child 终态查询），且预期"资源已被消费"类断言对应的错误回执（DENIED/not_owned 类）按语义解读就是核验通过，而不是待重试故障

## Short path
- 从恢复的汇报中列出载荷断言清单：推送到位、release 资产齐全、资格已被消费，各标注其唯一权威面
- 对每个权威面发一次只读核验：远端 fetch+HEAD 对比、release 资产与 SHA 查询、child 终态 status 查询
- 错误回执按语义当终态证据读：DENIED+not_owned 与"资格被推送消费"的预期一致，记为已核验，不重试
- 全部断言均有当前回执后才向用户报告"结果已出"，逐字引用 commit id 与 SHA256
- 停止：不为已核验项追加补充轮询或幂等复读

## Stop conditions
- 汇报中每条载荷断言均有本会话当前回执逐字支撑
- 用户只问未来动作、不涉及过去完成状态时，跳过回溯核验

## Verification
- 报告中的 commit/SHA/资产名与核验回执逐字一致
- 错误回执的语义解读与恢复上下文中的预期终态一致（是被消费，不是丢失或故障）

## Counterexamples
- 断言在当前上下文已有可见回执（如刚收到的终态 status）→ 直接引用即可，复读幂等终态回执是浪费
- 用户问"接下来做什么"而非"结果出了吗" → 无需回溯核验过去状态
- 断言关于系统内部机制/数据形态而非外部完成状态 → 走权威定义面裁决，而不是在线只读核验
