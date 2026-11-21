---
method_id: verify-cross-lane-content-identity-via-authoritative-hash-not-foreign-sh-919fc95ad6e2
name: verify-cross-lane-content-identity-via-authoritative-hash-not-foreign-sha-resolve
description: 协调/裁决消息断言『当前内容与另一 lane 的提交一致』并给出权威内容标识（tree/blob 哈希或显式身份标记）时，身份核验的机制是：在点名位置用一次复合只读探针取回 HEAD/tree/清洁状态/身份标记，逐字比对即收口；绝不通过本地解析外来 SHA 来构造证据（异 lane 对象通常不在本仓，解析必报 unknown revision）。若外来 SHA 探针失败或回执自相矛盾（exit 0 + fatal stderr），而该事实已被更早的标记/哈希确认，则引用已持证据继续，不重试同事实变体。身份收口后立即进入流水线下一步（CAS→门禁），不滞留验证阶段。
aliases: 怎么证明与另一条lane的提交相同, 跨worktree内容一致性核验, 引用对象不在本仓库里, revert后的基线怎么核对一致, 采信协调插话中的同一性断言
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:632:6b4174b5209e280d9b1e
evidence_refs: learning:learn:65e94e22cb63
created_at: 2026-11-17T09:53:22.009918+08:00
updated_at: 2026-11-17T09:53:22.009918+08:00
---
## Trigger
协调/裁决消息给出『与另一 lane（外来引用对象）的提交一致』的身份断言及权威内容标识（tree/blob 哈希或显式身份标记），且须在 CAS/lane_update 等写步骤前完成身份核验。

## Discriminator
点名位置的定点探针已返回身份标记（X_IDENTICAL_TO_<基线> 类回执）或本地 tree 哈希与插话权威值逐字一致——身份未知量此刻已收口；同时外来 SHA 属另一 lane 的对象库，通常不是本地可解析对象（解析将报 unknown revision / not in the working tree）。

## Short path
- 在点名位置一次复合只读探针取全关键事实：rev-parse HEAD、HEAD^{tree}、worktree 清洁状态计数、目标文件对给定基线的身份检查（拿到显式身份标记）
- 回执各值与插话给定的权威值逐字比对，全部一致即身份收口——不再追加探针
- 直接进入流水线下一步：带 expected_version 的 CAS 更新（失败即 HOLD），随后对精确新 head 启动全新独立门禁审查
- 若对外来 SHA 的探针报『本地不可解析』或回执自相矛盾（exit 0 + fatal stderr）而该事实已被更早标记/哈希确认：引用已持证据前进，不重试变体

## Stop conditions
- 点名事实全部与本地回执逐字一致 → 身份收口，验证阶段结束，进入 CAS/下一步
- 任一不一致（HEAD/tree/清洁状态/身份标记）→ HOLD，不写共享状态，回报裁决方
- 失败探针所指向的事实已被更早权威标记/哈希确认 → 不再重复核验该事实
- 外来对象报未知修订 → 视为对象位置信号（在异 lane 库），不在本 lane 继续解析

## Verification
- 回执中 HEAD、tree、清洁状态值与协调消息权威值逐字一致方可执行写步骤
- 最终汇报声称『一致/相同』时，引用的证据必须是实际取得的标记或哈希，不得以失败的 diff 充当证据

## Counterexamples
- 外来对象在本仓可解析（历史已合并/共享完整历史）：对它做路径限定的 diff 更强更省，不应绕开直证
- 消息未给权威哈希/标记且身份真实存疑：必须到对象所在地取证（对应 worktree 的 git show <SHA>:path 或 fetch），标识比对不适用
- 事实未被任何更早探针确认过：失败的 diff 本身就是信息，必须排查原因，不能径直归为已验证
- 评审结论被反证挑战、需在钉死的冻结 SHA 重取证的再裁决场景：属冻结锚点类另一方法，不套用本卡
