---
method_id: triage-gate-qualification-against-raw-review-verdict-and-authoritative-t-03ac6b83cfd7
name: triage-gate-qualification-against-raw-review-verdict-and-authoritative-truth
description: 闸门/编排器把子代理评审包装成 qualification 并返回 REVISE，且 reason 归因于 verdict 解析/不完整时：先读子代理原始输出确认真实结论（如『结论：通过 P0=0 P1=0』）；对冻结材料中与操作前提冲突的事实断言（『零增量/空操作』）用权威来源一次性核实（如 ls-remote）裁决物理真值；据此分类行动——实质发现→返工，词形不匹配→同目标重试一次，取证失真→按真值继续。不针对无法观测的闸门内部算法（merge-base 计算）做本地诊断链，该类调查通常以『依据不明』收场且不改变行动。
aliases: 闸门 REVISE 但子代理说通过, verdict 解析不完整 别深挖, 先读子代理原始结论, 零增量说法 用 ls-remote 核真值, 词形不匹配 原样重试一次
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:958:56f295fee18bfea72917
evidence_refs: learning:learn:d454ee9716ec
created_at: 2026-10-16T07:15:19.769805+08:00
updated_at: 2026-10-16T07:15:19.769805+08:00
---
## Trigger
自动审查闸门（如 git_push 准入）基于下游子代理的评审文本返回 REVISE/失败回执，而 reason 指向 verdict 词形解析或不完整（例：review_verdict_incomplete_or_not_pass），或包装后的 qualification 与可读取的子代理原始结论互相矛盾

## Discriminator
两条当时已可见的事实即可收窄：(a) 回执 reason 字符串本身把失败归因于『verdict 不完整/未解析』而非实质拒绝；(b) 子代理原始输出末行明确给出正面结论且仅含非阻断级发现（P0=0/P1=0、仅 P2 观察项）。二者并置把候选空间从『评审未过/操作对象状态错误/需返工』缩为『编码不匹配或取证材料失真』，后者只需一次权威真值核对（ls-remote 目标远端）即可裁决

## Short path
- 闸门回 REVISE：先不返工、不改产物，取底层评审者原始输出，读出其实际结论行与发现分级（未知量：评审实质是否通过）
- 对材料中与操作前提冲突的断言（如 repo_head==merge_base、零增量）做一次权威核实：ls-remote 目标远端，用物理真值裁决『是否空操作』，顺带完成既定的目标核对步骤（未知量：操作是否实质且必要）
- 按分类行动：实质发现→修复后重审；结论正面但词形非规范→按既有先例格式同目标重试准入一次（可先用一次事件流查询确认同管线近期有成功先例，替代对闸门内部算法的黑盒诊断）；材料失真但真值支持操作→随重试一并推进
- 重试 PASS→执行操作→ls-remote 复核最终真值并报告；若第二次仍因词形失败，停止重试、升级或换用能产出规范 verdict 的通道

## Stop conditions
- 子代理原始输出不可得且权威来源无法核实材料断言：不盲目重试，升级人工/换通道核验
- 同一解析类失败在重试一次后复现：判定为确定性词形约束，停止重试，改为产出规范词形
- 权威核实推翻操作前提（如远端已包含目标提交、操作确为空操作）：不执行操作，改为向用户报告状态差异
- 重试前后 candidate/target 指纹不一致：操作对象已被偷换，停止并重新走审

## Verification
- 重试使用与首次完全相同的 candidate/target 指纹，确认是同一操作对象
- 操作执行后权威状态复核一致（如 ls-remote 远端 SHA == 推送后本地 HEAD）
- 在最终回复中显式陈述包装 qualification 与原始结论的矛盾及裁决依据（真值来源、先例证据），保持可审计

## Counterexamples
- REVISE reason 引用实质发现（P0 泄漏、指纹不符、范围缺失）：必须返工，重试等于逃逸闸门
- 底层评审输出退化为空壳且无权威真值可对照：重试是赌博，应按评审契约自执行或升级，属于另一方法场景
- 权威核实显示操作真是空操作（远端已含目标提交）：正确动作是停止并报告状态，而非重试或强行执行
- 闸门文档明确只接受单一规范 verdict 词形且失败可确定性复现：解法是规范词形本身，重试无收益
