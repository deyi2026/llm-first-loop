---
method_id: port-named-artifact-live-truth-first-d81bc21f2ade
name: port-named-artifact-live-truth-first
description: 当任务要求把一个被点名的本地工具的能力扩展/移植到另一后端时，权威事实只有两条边：制品自述面（docstring/help/config）与现场真值（正在运行的服务身份 + 相关文件 VCS 状态）。先沿这两条边收敛出『能力面 vs 实际漂移』的差距——漂移往往就是任务本身；知识层检索（docs/记忆）在这两条边解释不了所需概念之前不启动，一次未命中后不得换参数重试同一来源。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:146:5ef4fb46bc77220c6b34
evidence_refs: learning:learn:15209f8a793a
created_at: 2026-09-20T17:21:00.371822+00:00
updated_at: 2026-09-20T17:21:00.371822+00:00
---
## Trigger
用户请求点名某个已存在的本地工具/制品，并要求把其已有能力扩展、移植或对齐到另一后端/形态（如『把我们已做好的X能力赋能支持Y，工具也进一步完善支持Y』）

## Discriminator
一次目录列举已同时暴露：被点名制品本体、其 config/launch 脚本/测试，以及目标后端的伴生制品（同目录下的 llama 基准文件等）——两侧事实均已在本地可见时，知识层宽检索无法再缩小任何未知量；此时若前一次 docs 检索已未命中，重试同源检索即视为扩散

## Short path
- 读被点名制品的自述面（头部 docstring/help + 主 config.json）→ 求解未知量：现有能力面是什么、声明管理什么
- 探测现场真值：服务列表 + 端点身份元数据（如 /v1/models 显示的真实 format/owner）+ 相关文件 git 状态 → 求解未知量：声明与实际的漂移在哪、目标后端目前是否处于手工/未纳管状态
- 仅按 (1)(2) 暴露的扩展点定向阅读实现片段（如 plist 构建、健康探测、switch、models 扫描），不整读全文件
- 在后端抽象层实现扩展，先跑既有测试 + 只读现场校验 + dry-run，全部通过后才执行任何线上变更
- 漂移闭合、双后端行为验证一致即停

## Stop conditions
- 能力面、现场服务身份、VCS 状态三者齐备且相互解释（差距被完整定义）→ 停止发现，进入实现
- 制品自述面与现场均无法解释的剩余概念 → 才允许单次知识层检索；未命中即换 provenance 边，而非换查询词重试
- 所需变更已通过测试 + dry-run 验证且原后端回归全绿 → 停止验证枚举

## Verification
- 端点身份元数据（真实 format/serving backend）与 config 声明的后端一致
- 目标后端不再存在未纳管的手写制品（git status 中无游离文件）
- 原后端分支回归测试全绿；switch/dry-run 输出与预期迁移序列一致后才做线上变更

## Counterexamples
- 用户问概念性/跨项目问题且未点名任何本地制品 → 知识层检索才是合理第一跳
- 制品是外部项目的 vendored 拷贝、真实 schema 在上游 → 本地自述面可能过期，须对照上游/运行时版本而非只信本地表面
- 现场探测非只读或有生产风险（探针可能触发状态变更）→ 回退到日志/git 等记录性证据，不执行 live 调用
