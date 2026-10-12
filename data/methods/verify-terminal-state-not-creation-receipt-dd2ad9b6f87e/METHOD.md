---
method_id: verify-terminal-state-not-creation-receipt-dd2ad9b6f87e
name: verify-terminal-state-not-creation-receipt
description: 对存在独立终态翻转步骤的多阶段流水线（发布草稿→正式发布、标记 Latest、部署），上游成功回执不等于完成。当同类操作有卡死在终态的历史实例（旧版本停在 draft 从未发布），或用户提出完成性问句时，先用权威查询确认终态，缺失则只补一步定向终态命令，并以权威输出中可见的状态变化收尾，而非仅凭退出码或早前回执。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:623:407a7b1f581fd5d78aa8
evidence_refs: learning:learn:b587aba94302
created_at: 2026-09-19T08:43:19.101541+00:00
updated_at: 2026-09-19T08:43:19.101541+00:00
---
## Trigger
多阶段状态变更流水线到达“对象已创建/门禁已过”阶段，或用户问“是不是完成了？”，且该流水线存在独立终态步骤（draft→published）或历史实例曾卡在同一终态（如旧版本一直是草稿、只有更早版本成为正式 Latest）。

## Discriminator
当时已知的可观察事实：当前 Release 对象已创建但仍是 draft（未发布），且同一流水线此前 v0.6.11/v0.6.10 正是停在草稿未发布、只有 v0.6.13 成为正式 Latest。这把“完成了吗”从复盘整条 42 轮流水线缩小为一个可查询的未知量：当前 release 的 published/Latest 终态。

## Short path
- 把“完成”翻译成用户所需的对外可见终态（published 而非 draft、Latest 标记、tag 指向预期 commit），解决未知量：什么才算完成。
- 用权威来源一次性查询该对象终态（如 gh release list/view 中的 draft/Latest 列），解决未知量：终态是否已达成。
- 若未达成，只执行缺失的那一步终态翻转命令（如 gh release edit --draft=false --latest），解决未知量：补齐最后一公里。
- 在同一权威输出中回读终态标记；当退出码为 0 但 stderr 带解析告警（如 Unknown JSON field: isLatest）时，必须以输出中可见的状态变化为准，解决未知量：翻转是否真正生效。
- 终态确认即停止；若存在有意延后的终态（留给评审的草稿、需等并行会话工作落盘后再 re-publish），显式报告前置条件，不默称完成。

## Stop conditions
- 权威输出显示目标对象已处于所需终态（已发布、Latest、绑定预期 commit）。
- 终态翻转被有意延后（草稿待评审、需等另一活跃会话工作落盘/隔离）——此时停止推进，显式报告延后原因与解除前置条件。

## Verification
- 从权威列表/详情重新读取状态，看到目标对象带上终态标记，而不是依赖早前成功消息的记忆推断。
- 命令退出码 0 且 stderr 含告警时，确认工具自身输出中已可见目标状态（如 Latest 标记出现在 release 列表）才判定生效。

## Counterexamples
- 创建即终态的原子命令（无 draft 阶段）：创建后一次验证即可，再补 publish 步骤会报错或造成重复操作。
- 草稿正是用户要求的终态（分阶段评审流程）：不应翻转为 published/Latest。
- 终态刚在上一步工具输出中验证过且其后无任何变更：再次查询属于无信息重复动作，应直接回答完成。
