---
method_id: exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-3249731118b4
name: exit-poll-when-receipt-not-pending-route-missing-verdict-fields-to-child-result
description: 门禁裁决是命名字段的合取（正式 qualification ∧ Reviewer 真实终态 ∧ PASS ∧ 关键计数为 0 ∧ 材料 SHA 绑定）时，若某轮轮询回执只带部分字段（如 qualification+SHA）且无 pending/未结算标记：循环的继续条件只看回执自身的 pending 信号，不看"我还缺哪些字段"。非 pending 即退出既定 wait+status 循环，把每个缺失字段路由到能供应它的观测通道，child 终态与关键计数来自按 child_id 查询 child 原始结果（含完整评审报告）。对 schema 冻结的通道重复轮询只会烧掉有界轮次预算、拿到重复回执。与"pending 就继续轮询"、"确实拿不到就如实上报缺失"是三个不同分支。
aliases: PASS了但查不到P0P1计数去哪补, 回执还是老样子还要不要再等一轮, 怎么确认审查子任务真的跑完了, poll拿到的结果一模一样该换渠道吗, 放行条件还差一项证据从哪拿, 子代理审查完成了吗在哪看
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c69dd0cf-6987-4886-90f5-7a86a88dede6:0:a5945e765757e7c4f771
evidence_refs: learning:learn:bc85845ca7e9
created_at: 2026-10-24T13:08:19.102529+08:00
updated_at: 2026-10-24T13:08:19.102529+08:00
---
## Trigger
对单次授权、禁止重复 start 的子任务按任务书做有界 wait+status 轮询；最终放行条件是多个命名字段的合取（正式 qualification 为真 ∧ Reviewer 真实 completed ∧ PASS ∧ 关键计数为 0 ∧ 材料 SHA 绑定）；status 回执返回了结论级内容（如 PASS）但既无 pending/未结算标记、也无终态与计数字段。

## Discriminator
第一份 status 回执的字段集与信号：只有 {candidate_sha256, qualification}，给出的是结论（PASS）而非进行中提示，"pending 就继续"的循环条件为假；同时 start 回执已在手的 child_id 指向能供应终态与计数的确切通道（child 结果查询）。重复 status 不可能凭空长出新字段。

## Short path
- start 一次、逐字参数 → 记 child_id 与 candidate SHA，核对等于冻结材料 SHA；拒绝或漂移即停，不重试 start。
- 按任务书规定时长真实 wait → status(child_id=精确 id)。
- 回执为 {SHA, qualification:PASS} 且无 pending 标记 → 轮询循环继续条件不成立，退出循环；显式列出仍缺的合取项：真实终态、关键计数。
- 按 child_id 查 child 结果 → child_state=completed + 完整评审报告（含关键计数与逐项结论），一次性补齐缺失项。
- 逐项核对合取（start 供 SHA 绑定、status 供 qualification、child 结果供终态+计数），全真才宣告门禁满足；在本次授权范围内收口，不越权启动后续动作。

## Stop conditions
- 合取各项均由对应权威回执逐项验证为真，且各来源相互一致（材料 SHA 绑定不漂移）。
- 任一回执出现 pending/未终态信号 → 回到任务书规定的有界 wait+status 循环，不把半成品 child 输出当终态。
- start 被拒绝或 candidate SHA 与冻结材料 SHA 漂移 → 立即停止，不重复 start。

## Verification
- 收口时每个合取项能指认其来源回执：start（SHA 绑定）、status（qualification）、child 结果（completed + 关键计数）。
- child 报告引用的材料/candidate SHA 与 start 回执一致，无指纹漂移。
- 没有任何合取项以"未见到反例"、记忆或推断代替权威回执。

## Counterexamples
- 回执带 pending/尚未结算提示、或 child_state 非终态 → 属"继续有界轮询"分支：此时读 child 原始结果只会拿到半成品评审，应按任务书继续 wait+status。
- qualification 本身可疑（如 REVISE 且 reason 归因 verdict 解析/不完整，或与冻结材料的事实断言冲突）→ 属闸门失真分流：除读原始输出外还要用权威来源核实冲突断言再决定行动，不只是补齐字段。
- 不存在 child 结果查询通道、且轮询回执长期只含部分字段 → 不得无限轮询等新字段，应如实上报缺失的合取项、不宣布裁决完成。
- 单轮回执已含全部合取字段（终态+计数+SHA）→ 直接收口，不发多余查询。
