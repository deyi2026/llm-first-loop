---
method_id: check-rule-precondition-before-gated-completion-f26936021525
name: check-rule-precondition-before-gated-completion
description: 收口带闸 Goal/task 时，先对照治理规则的完成定义，检查自己刚落盘回执中的执行前置字段（如 executed=false、执行后指针为空）：若规则把完成定义为『有效回执 AND 某执行动作 X 已实际发生』，而本轮 X 被明确禁止或延后，则不要发起 complete 转换，也不要迭代证据引用格式去硬闯终局证据门——被拒的本质是语义前置未满足，表面错误（如 unsupported_ref）只是巧合的格式抱怨。以 checkpoint+阶段报告收尾，保持 Goal active，把执行 X 列为下一显式授权步骤。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b3627445-5547-4a84-801d-62f5b227a751:303:5e99247e7cea24d38954
evidence_refs: learning:learn:e5d6db83719c
created_at: 2026-10-17T01:38:58.693416+08:00
updated_at: 2026-10-17T01:38:58.693416+08:00
---
## Trigger
治理规则将任务完成定义为『有效审查回执 + 执行动作 X 已实际发生』（例：并入 main 才算入账，未并入转 blocked 而非 done），本轮用户或规则明确禁止/延后 X，而验证工作与回执已全部落盘，Agent 正准备把 Goal/task 置为 done/complete。

## Discriminator
发起收口前已存在三条可判事实：(a) 已读的规则原文明确写『未实际执行 X 不得声称完成，转 blocked 而非 done』；(b) 自己刚写的回执如实记录执行字段=false（执行后指针为 null）；(c) 用户指令本轮禁止 X、待下一阶段显式审批。任一条都预先判定 complete 语义无效；证据门报的引用格式错误不是根因。

## Short path
- 回执落盘后暂不发起 goal complete：先读自己回执的执行前置字段，对照规则完成定义判断本轮是否具备收口语义
- 若执行前置未满足（X 被禁/延后），直接跳过 complete 尝试，不进入引用格式修复循环（snapshot/artifact ref 迭代）
- 用 checkpoint 记录完整事实链（三态裁决、精确 SHA、child_id、回执位置、下一最小步骤）作为本轮事实终态
- 输出阶段报告：准确裁决+证据+精确引用+待显式授权的下一步（执行 X 后回执补记执行字段，届时才发起 complete）

## Stop conditions
- 规则完成定义的执行前置已满足（X 已执行、回执已补记执行后状态）→ 才发起 complete 并引用稳定 artifact 回执
- 用户显式豁免/暂缓并留痕 → 按规则显式路径处理，不静默跳过也不假 complete
- 本轮报告已含准确裁决与下一授权步骤 → 停止，不追加确认性工具调用

## Verification
- 回执执行字段与真实系统状态一致：未执行就写 false，绝不预填执行后指针
- 执行前置为 false 期间，任何输出不出现 done/complete/已执行 X 的声明
- 仅当执行前置确实已满足而证据门仍拒绝时，才把拒绝归因于引用格式并做 snapshot 引用重试

## Counterexamples
- 规则完成定义只要求有效回执、无执行条款 → 证据门拒绝就是纯格式问题，应修引用格式后重试，而非保持 open
- 拒绝源于证据存储瞬时不可用等基础设施故障 → 稍后重试即可，不做语义重构
- X 是本轮自身职责且未被禁止 → 前置未满足说明任务没做完，应去申请授权并执行 X，而不是只 checkpoint 收尾
- 无治理规则约束的普通任务 → 直接按用户目标判定完成，无需前置字段检查
