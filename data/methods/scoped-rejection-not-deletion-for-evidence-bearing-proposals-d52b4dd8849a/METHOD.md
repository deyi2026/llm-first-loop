---
method_id: scoped-rejection-not-deletion-for-evidence-bearing-proposals-d52b4dd8849a
name: scoped-rejection-not-deletion-for-evidence-bearing-proposals
description: 在 append-only 审计账（JSONL 建议流）里撤回/废弃一条提案时，物理删除不是安全操作：记录内嵌的已验证证据（实测样本、方案漏报对比）独立于提案结论，删行即毁证且日后无人可复核。正确闭包 = 状态机终态（rejected）+ 结构化理由字段，且理由必须分区：撤回的是方案/做法、仍然成立的是已验证事实与未修复缺陷、未改动的是相关代码，并附重启时应走的层级建议。先用一次定义面读取拿齐终态词汇/理由字段/owner 权限断言，替代多轮 grep 用户口语词（如「废弃」）；流转后回读核验后置状态，并如实汇报「没做的事」。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:850:2b840ef6490e6aca6e78
evidence_refs: learning:learn:fa5926db465b
created_at: 2026-10-13T23:19:04.889736+08:00
updated_at: 2026-10-13T23:19:04.889736+08:00
---
## Trigger
用户要求把一条已提交的提案/建议「标记为废弃或删除」，而该记录存于 append-only 账本（JSONL/审计流），且系统状态机存在终态+理由字段（如 rejected/rejected_reason）

## Discriminator
两条当时一次查询即可得的事实决定走向：① 账本是否 append-only 且删除不是一等操作（状态机定义面/grep 已显式列出 pending_review→accepted/rejected 与 rejected_reason 字段）；② 目标记录内容是否含独立于提案结论的已验证证据（量化实测、样本清单、方案对比）。两者皆真 → 必须标记而非删除，且用户口语的「废弃」应映射到系统终态词汇 rejected

## Short path
- 按状态过滤（status=pending_review）一次定位目标记录并读全文，确认其证据内容、归属 session 与 requires_human 标志
- 一次读状态机定义面（模块 docstring + review/transition 函数）拿三件事：合法终态词汇、理由字段机制（rejected_reason/reason_history 追加不覆盖）、owner/权限断言——把用户口语「废弃」映射到 rejected，不再多轮 grep 同义词
- 判定 mark vs delete：记录含独立已验证证据 → 必走状态流转+理由字段；仅当记录为纯噪音且删除是一等操作才考虑删
- 理由三段分区落盘：撤回的方案范围 ≠ 仍成立的已验证事实（缺陷真实存在且未修复）≠ 未被改动的代码现状；附重启时应走的根因层路径建议，防止后人把撤回误读为否定事实或再叠一层特判
- 流转后回读验证后置状态（rejected、reviewed_at 有值、全库 pending 计数归零），汇报时明确列出「没做的事」（被提案指向的缺陷/代码原样未动）

## Stop conditions
- 目标记录已达终态且 rejected_reason 非空落盘，回读确认
- 全库同类 pending 计数已重新核对（避免对「是否最后一条」作未验证断言）
- 已向用户区分「撤的是提案不是缺陷」并披露未改动范围

## Verification
- 回读该记录：status=rejected、rejected_reason 非空、reviewed_at 有时间戳
- 重新统计全库状态计数，确认无遗留 pending_review
- 确认被提案指向的源码 diff 为零，与「只撤提案、不改缺陷」的声明一致

## Counterexamples
- 记录只是重复提交/空建议，不含独立已验证证据，且系统原生支持删除或压缩 → 直接删除或合并，无需三段式理由
- 账本是可变数据库且已有原生软删/tombstone 语义 → 用原生语义即可，不必自造分区理由
- 提案本身从未做过验证、无可保留事实 → 一句话普通 rejected 理由即可，分区反而制造噪音
- 用户明确要求物理删除且策略允许 → 遵从执行，但先把已验证事实迁移保存到别处再删，不静默毁证
