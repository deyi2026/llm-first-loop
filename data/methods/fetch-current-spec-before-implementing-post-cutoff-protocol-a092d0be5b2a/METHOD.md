---
method_id: fetch-current-spec-before-implementing-post-cutoff-protocol-a092d0be5b2a
name: fetch-current-spec-before-implementing-post-cutoff-protocol
description: 当目标外部协议/标准的当前修订晚于训练知识，或对其 wire 细节（握手、协商、头、_meta 键、错误结构）不能逐条自信给出时，把先验记忆降级为不可信：先抓取本地设计文档点名的官方规范原文，再让每个 wire 级实现决策逐条对应规范文本；规范未覆盖或页面截断处只补抓缺失段，不用旧版记忆填空。本集据此一次性交付 MCP P1-B 双时代实现（modern 无握手/无会话 + legacy 回退），57/57 测试绿；若按旧握手先验直接实现，将在集成测试失败后返工并被迫补抓同一批规范，路径显著更长。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:226:d9ac6439447faba46db8
evidence_refs: learning:learn:369c811dc17f
created_at: 2026-10-09T11:40:38.541652+08:00
updated_at: 2026-10-09T11:40:38.541652+08:00
---
## Trigger
即将实现或对接外部协议/标准/第三方 wire 格式（如 MCP、OAuth、OpenAPI），且本地设计文档或回执显示其当前修订版本晚于训练知识，或对握手/版本协商/错误结构等 wire 细节不能逐条自信给出时。

## Discriminator
写实现代码前当时即可检查的事实：文档引用的规范修订号（本集 2026-07-28）是否晚于训练知识、是否含破坏性变更（去会话/去握手/新增 server/discover）。若目标修订新于训练知识或任一 wire 细节无把握，先验记忆即不可作实现依据，必须先取规范原文——该判定在进入实现前成立，不依赖后续测试结果。

## Short path
- 从本地权威设计文档确定实现范围与其点名的规范修订/参考（本集 §11 P1-B → versioning/stdio/streamable-http/changelog）
- 并行抓取被点名规范页，逐条提取 wire 事实（server/discover 探测、_meta 键名、UnsupportedProtocolVersionError 的 data.supported、HTTP 单端点 POST、subscriptions/listen）
- 每个实现决策映射到已抓取规范文本；被截断页面只补抓缺失段（必需头/错误语义），不用先验补空
- 以本地既有公开契约为实现边界（如 P0 契约不变），新协议行为用覆盖新旧两时代的集成测试验证
- 交付时声明所依据的规范修订与未做余项，停止

## Stop conditions
- 所需 wire 细节均已取得且有规范页面/章节出处，且实现边界（既有契约）确认不变
- 确认协议版本早于训练知识且本地代码/测试已固化契约，此时以本地定义面为准，无需外抓

## Verification
- 每个非平凡 wire 决策能指出对应规范原文出处
- 新旧两时代行为均有集成测试覆盖（本集 57/57 MCP 测试 + P0 回归 23 全绿）
- 机械预检：从本地文档提取规范修订日期并与训练知识截止比较，晚于即强制先抓规范再写实现

## Counterexamples
- 协议修订早于训练知识且细节可自信逐条引用（如稳定 JSON-RPC 基础），不必为常识细节外抓规范
- 契约权威在本地代码/类型/测试（如保持内部公开契约不变）时，以定义面与调用点为准，规范只裁决协议层，不覆盖内部 API 设计
- 抓到的页面是营销/概览、不含 wire 语义时不能当实现依据，应改取规范仓库源文件或标准文本
- 网络不可用时不得静默以先验顶替，应显式声明不确定，并用探测式兼容路径（先 server/discover、失败再回退旧握手）并如实标注依据缺失
