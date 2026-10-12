---
method_id: filter-mirrors-and-name-collisions-then-read-canonical-endpoints-1f35dcf5cbad
name: filter-mirrors-and-name-collisions-then-read-canonical-endpoints
description: 在存在『运行时快照镜像（evals/**/results/runtime-*）+ 副工作树 + 历史目标同名编号文档』污染的代码库里，宽泛内容搜索会被旧拷贝和同号撞名刷屏。若目标记录已固定任务命名空间、且首次搜索已点名 live 模块路径，就不要再换关键词反复发现：先按路径与目标命名空间滤掉镜像根和跨线同号文档，再直接读『src 现行实现 + 对应设计文档章节』两个规范端点，验收由这两者导出，发现即终止。把『全库关键词枚举』压缩为『两次可验证读取』。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:405:1f2400eeb4cdb6c7c3a8
evidence_refs: learning:learn:2e7ea7bdd779
created_at: 2026-09-18T19:32:35.112691+00:00
updated_at: 2026-09-18T19:32:35.112691+00:00
---
## Trigger
启动一个迁移/重构类任务：仓库搜索空间含有捕获的运行时快照镜像、副工作树与历史目标的文档；同时已有 goal/task 记录定义了任务目标与验收标准（如『不残留双实现、行为契约不静默改变』）。

## Discriminator
当时已可见：① 首次内容搜索已给出 live 模块路径 llm_loop.memory.extractor（→src/llm_loop/memory/extractor.py），而大部分命中聚集在 evals/.../results/runtime-fc1-2794b2cd 与 .context-integrity-wt 两个非现行根下——是快照/工作树拷贝而非候选真值；② goal 记录已把本任务绑定为 TASK-0a2e29d8-002/GOAL-20260918-0a2e29d8，而命中的 r8-continuation-plan.md 从路径（injection-governance/r8）与行文（R8.23）即带另一条线的标记。这两条当时已知事实可直接滤掉噪声，只剩两个规范端点待读。

## Short path
- 从 goal/task 记录固定验收（不残留双实现、行为契约不静默改变），不再搜索可能不存在的『更详细计划记录』。
- 从首次搜索结果取 live 模块路径，直接读 src/llm_loop/memory/extractor.py——解决『现状实现与需保留契约』这一未知量。
- 在规范 docs/ 根下按文件名定位目标侧 SoT（learning-plane 设计文档的 P0-C 章节）——解决『要迁入的契约』这一未知量。
- 以这两个端点为约束实施迁移；期间忽略镜像根命中与同号跨线文档，除非规范端点信息不足。
- 落点后验证：测试回执 + commit/tree 与 live main 一致，验收点逐项打勾后停止。

## Stop conditions
- 两个规范端点（现行 src 实现 + 对应设计文档章节）均已读、验收清单可由其完整列出时，停止发现、进入实施。
- 报告所需全部事实（commit/tree 哈希、测试计数、契约条款）已从 live 树与规范文档取得并核验后停止。

## Verification
- 落点后以 git head/tree 与 live main 对照核验；测试计数来自 junitxml 等权威回执而非记忆。
- 引用的行为契约变化能在规范设计文档中定位到对应章节，证明是非静默变更。
- 确认没有任何镜像根（运行时快照/副工作树）文件被当作现状证据写进结论。

## Counterexamples
- 任务本身就是审计或逐字节比对快照/工作树（如收敛 disposition 比对）：镜像根即目标物，必须读，本方法不适用。
- live 树缺少目标工件、快照是唯一来源（如丢失代码找回）：镜像命中升级为权威线索，应当沿用它。
- 干净单根仓库、无镜像与同号撞名污染：无需滤根，搜索命中目标后直接读即可，本方法退化为普通『读到即止』。
