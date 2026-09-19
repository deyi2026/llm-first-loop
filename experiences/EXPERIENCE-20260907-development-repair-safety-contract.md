---
title: 开发与修复防退化：先保 exact source、核真实 provider-view、按当前 runtime qualification、最终 candidate 实测
scenario: 2026-09-07 连续性与本地 GGUF 优化中，先后出现 reasoning 在 4096 输出预算内耗尽导致空响应、resolved episode 过早退休导致“刚说完就忘”、截断内容仅 tail/overwrite sidecar 导致以后无法 exact recovery、附件第二次回读仍重复展示截断、preview 冒充全文摘要、AttachmentStore 层级错置、架构守卫因 unstaged HEAD fallback 产生假绿等事故。
root_cause: 多个表象问题共同来自四类错误：① 把历史/另一 runtime 的默认配置当成当前事实；② projection/truncation 先于 durable exact capture；③ 程序越界替模型做语义取舍/恢复判断；④ 验证没有覆盖最终 staged/isolated candidate 的真实状态。
solution: 以 docs/DEVELOPMENT_REPAIR_SAFETY.md 为详细 SoT，并提升为 RULE-AI-24。维护改动前固定六问：完整事实源是否存在；模型是否有 stable ref 可 exact 回读；模型实际 provider-view 是否包含预期信息；参数是否在当前 runtime qualification；程序是否越界接管语义判断；最终 gate 是否验证真正 staged/isolated candidate。真实事故必须留下 regression test；摘要永远低于 exact source；跨 runtime 只复用实验起点，不复用 parity 结论。
evidence: "8a45047, 9766aee, 47556cb, 957b417, deea2b5; docs/DEVELOPMENT_REPAIR_SAFETY.md"
tags: [development, repair, anti-regression, continuity, truncation, runtime-qualification, provider-view, candidate-gate, architecture-boundary]
source:
  kind: incident_synthesis
  rule: RULE-AI-24
status: archived
promoted_to_rule: RULE-AI-24
created_at: "2026-09-07T23:44:00+08:00"
updated_at: "2026-09-07T23:44:00+08:00"
---

该条只保留事故证据与来源链。当前行为权威是 RULE-AI-24；不要把本经验当作普通 active 策略自动注入。
