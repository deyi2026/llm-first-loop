---
method_id: definitive-negative-receipt-closes-fallback-branch-c1fe458f6e76
name: definitive-negative-receipt-closes-fallback-branch
description: 指令常含回退条款：『先检查前置条件；若检查不可用则按持久回执+复核继续』。当检查实际返回带机器 reason 的确定性否定（如 DENIED: review_child_not_owned），这不是『不可用』，而是对前置问题的否定回答；回退分支只适用于错误/超时/未判定。应把 reason 映射到它否定的前置轴：若否定的是会话/所有权绑定，而门禁命令恰需该绑定，则命令已被预判拒绝——不再尝试，也不用其他轴复核成功（如 SHA 匹配）去对冲一个已知的绑定失败，直接按用户预设的『拒绝即停』收口，把是否重新发起的决策交回用户。若 reason 否定的是材料轴（如 sha_mismatch），才用本地权威复核裁决。本集实测：ownership DENIED 后仍执行 ci_gate，被 Rule28 以同轴理由阻断，白烧一次注定失败的调用。
aliases: 被明确拒绝算不算检查不可用, 资格不属于本会话还要试门禁命令吗, DENIED带reason还能走回退分支吗, 预判会被Rule28拦还要不要发命令, 用SHA匹配对冲所有权拒绝
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0dd3f09c-3d0d-4edd-baa8-f4f1aa1bf48c:0:c3b64b77f7a6435a9e82
evidence_refs: learning:learn:1f0b77c539c5
created_at: 2026-10-24T16:45:37.267675+08:00
updated_at: 2026-10-24T16:45:37.267675+08:00
---
## Trigger
指令给出『先检查前置条件；若检查不可用则按持久回执+精确复核继续』的回退条款，且下一步动作是被独立审查/所有权类门禁保护的强命令，其执行前置条件正是该检查要确认的绑定关系

## Discriminator
检查回执的确定性类别：带机器可读 reason 的明确否定（qualification 字段 + reason 码，如 review_child_not_owned）= 已对前置问题给出否定回答；错误/超时/无裁决字段 = 未判定，才适用回退分支。进一步把 reason 映射到被否定的前置轴（会话所有权 vs 材料 SHA vs 资格撤销），只有被否定轴恰是门禁绑定所需的轴时，才可预判命令必被拒

## Short path
- 执行指令要求的检查动作（如 status），读回执是否带明确裁决字段 + reason 码
- 分类回执：错误/超时/未判定 → 走指令回退分支（持久回执+精确复核后继续）；确定性否定 → 进入停止分支评估
- 把 reason 映射到前置轴：所有权/会话绑定被否定，且门禁命令需此绑定 → 判定命令已被预判拒绝
- 不用其他轴的复核成功（SHA/HEAD 全匹配）对冲绑定失败，不尝试被门禁命令
- 按用户预设处置（拒绝即停、不绕过、不自行重发被禁止的 start）收口报告，把重新发起的决策权交回用户

## Stop conditions
- 回执为确定性否定，且被否定轴 = 门禁命令所需绑定 → 不发起该命令，直接按预设拒绝处置收口
- 用户明令禁止重新发起（如不得再调 start）→ 不自行发起，报告后终止
- 回执未判定（错误/超时/通道不可用）→ 本卡不适用，走指令回退分支

## Verification
- 若事后仍尝试被门禁命令，其阻断理由应与 DENIED reason 同轴（本集 Rule28 阻断语即『不存在覆盖…父会话的有效资格』），可反证分类正确
- 报告中明确区分『资格被撤销』与『资格所有权跨会话不可迁移』两种不同失败
- 确认全程未修改源码/门禁、未自行发起被禁止的重发动作

## Counterexamples
- status 调用真超时/通道错误（未判定）→ 回退分支适用，应按持久回执+精确复核继续，不得提前停
- DENIED reason 为 sha_mismatch（材料轴）→ 正确动作是本地权威复核材料是否变化后再分支，而非直接停死
- 用户指令未要求资格绑定父会话（仅绑产物指纹）→ not_owned 未必预判门禁拒绝，可先尝试一次
- 有历史证据表明该门禁对所有权判定有误报 → 一次验证性重试可辩护
