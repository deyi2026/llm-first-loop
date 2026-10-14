---
method_id: falsify-error-message-attribution-via-emitter-and-state-truth-8c08c0091979
name: falsify-error-message-attribution-via-emitter-and-state-truth
description: 排查'被拒绝/失败'类错误时，若错误文案点名某机制（如 run lease fenced），不要直接沿该机制深挖：① grep 文案字面量，枚举产出同一串的所有 gate（共享硬编码文案可能掩盖真实条件分支）；② 直读被点名机制的权威状态记录（磁盘 state/registry/log）。状态健康而错误仍确定性复现 ⇒ 文案归因已证伪，真因在共享同一文案的其他 gate。配套：receipt 只含 args 哈希时，先从 event log 还原原始调用参数再断言工具缺陷；文档/playbook 的'这是设计'断言若证据同源于该文案，同样视为待证伪假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:737:ff99dfce9291f1d63c30
evidence_refs: learning:learn:1a156fe0ba1d
created_at: 2026-10-14T17:26:22.851900+08:00
updated_at: 2026-10-14T17:26:22.851900+08:00
---
## Trigger
调试中错误/拒绝文案点名具体机制（lease/token/permission/quota/timeout 等），且满足其一：该文案在源码中是多处共享的硬编码串；或被点名机制存在可直读的权威状态记录（磁盘 state、注册表、事件日志）。

## Discriminator
grep 错误字面量后的发射点结构（单点单条件 vs 多文件/多 gate 共享同一串），叠加被点名机制的权威状态真值：若状态记录健康（如 lease 全部 acquire→renew→settled 正常）而错误仍 100% 复现，则文案归因为假，真因在共享该文案的其他条件分支（如 generation/registry 校验）。

## Short path
- 记录失败回执原文，列出文案点名的机制与隐含归因；未知量：这条文案由哪段代码、在哪些条件下产出？
- grep 文案字面量 → 读所有发射点，枚举产出同一串的全部 gate/条件（不要停在第一个命中）
- 直读被点名机制的权威状态记录，判定状态与失败叙事是否一致
- 一致 → 沿该机制排查；不一致 → 假设转移到共享文案的其他 gate，写最小 red 复现测试定位，再修复转 green
- 验证修复未触碰原被点名机制，并把结论回写推翻基于同源文案的旧断言（playbook/文档）

## Stop conditions
- 发射点唯一且条件即被点名机制，或权威状态记录确认该机制确实失败（如 lease 真过期/被夺）→ 归因成立，直接沿该机制排查，停止证伪分支
- 已用最小 red→green 测试把根因钉到具体 gate，且修复不涉及原被点名机制

## Verification
- 修复在不改动原被点名机制的情况下使失败用例转绿（归因证伪的最终确认）
- 复读权威状态记录与最终结论一致；同一文案的所有发射点语义已厘清，并撤销文档/playbook 中基于该文案的错误'设计'断言

## Counterexamples
- 权威状态记录显示被点名机制真实失败（lease 确实丢失/过期）→ 沿文案深挖就是短路径，本方法只添噪音
- 文案由运行时动态拼装、单点发射且带具体上下文（如含真实资源 ID）→ 归因通常可信，直接读发射点即可
- 外部黑盒系统（无源码可 grep、无状态记录可读）→ 只能行为级探测，本方法不适用
- 成功但空结果类异常：先从 event log 还原原始调用参数（receipt 常只有 args 哈希），排除显式参数差异（如 depth=1）后再怀疑工具缺陷——此时问题不在文案归因
