---
method_id: pre-classify-knowledge-card-by-verification-state-df1922e69f15
name: pre-classify-knowledge-card-by-verification-state
description: 向带类型门禁的经验/教训库沉淀浓缩知识前，先用写入时已知的验证状态（有无独立成功回执）一次性选对 record_kind：未验证内容直接走 lesson 通道，并在卡内预置一行可执行的当前性验证动作（如 grep 探针+预期结果）。避免默认提交最权威类型、被校验拒绝后再返工。本集两次 save_experience 被拒（experience 通道误用于 unverified 内容、lesson 卡缺验证动作行）本可在首写前用已知事实避免。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2d3fd645-2639-44ec-9f14-2a96c1c807fe:131:9e52300a14377f1e4689
evidence_refs: learning:learn:5011cb2f3e8f
created_at: 2026-10-14T12:58:39.957776+08:00
updated_at: 2026-10-14T12:58:39.957776+08:00
---
## Trigger
准备把一次任务的浓缩经验/教训写入带 record_kind 或验证等级校验的结构化知识库，且内容的验证状态在写入前已可自判（无独立成功回执、此前已自标 unverified）。

## Discriminator
写入前问一次『这条内容有没有≥一次独立任务的成功回执』：没有 → lesson/unverified；有 → experience。同时卡体必含一条可执行当前性验证动作（具体命令/路径/行号+预期输出），既满足卡片门禁，又防止浓缩结论在环境变更后变成错误答案来源。

## Short path
- 落卡前判定验证状态：内容仅一次应用、无独立成功回执 → record_kind=lesson、verification_state=unverified，一次到位不试探 experience 通道
- 卡内预置『当前性验证：<命令/探针> 应得 <结果>』一行，引用本次真实文件与行号而非泛化描述
- 提交一次；若仍被拒，把拒绝回执视为 schema 规格逐条补齐后重交，不换措辞空重试
- 落库成功后如实保留 unverified 状态，待第二次独立应用再升级

## Stop conditions
- 写入回执显示 record_kind 与内容实际验证状态一致，且卡含可执行验证动作行
- 目标存储无类型/验证门禁时直接写入，不做前置分类开销

## Verification
- 检查回执的 record_kind 与 verification_state 和内容证据等级一致（无回执≠已验证）
- 执行卡内验证动作行（如 grep -n 关键字 路径）确认当前仍命中预期结果

## Counterexamples
- 内容已有多任务独立成功回执 → experience 是正确通道，强走 lesson 反而降级错误
- 一次性随手笔记、不打算被未来检索复用 → 无需当前性验证动作，前置分类是纯开销
- 存储无 record_kind/验证门禁且无验证状态语义 → 本方法不适用
