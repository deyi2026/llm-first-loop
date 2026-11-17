---
method_id: translate-external-criteria-to-local-naming-then-probe-live-state-4a8b43abc928
name: translate-external-criteria-to-local-naming-then-probe-live-state
description: 评估判据来自外部概念框架（文章/规范/他山之石）时，不要拿外部词汇直接检索本系统 store：首次 miss 回执列出的条目标题会暴露本地词汇体系。先把每条判据翻译成本系统命名面（config 键/模块词根/状态工具维度），行为证据打 live 状态面，机制证据用子系统词根做 scoped 实现树检索，逐条给 verdict+可回指证据+按投入产出排序的建议。
aliases: 拿外部文章框架评自己系统, 对照别人文章做差距评估, 检索不中先换本地词汇别换同义词, 评估先打运行时状态再看代码, 外部判据翻译成本地模块名
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9a21b8fd-48b7-47a5-89f5-4b9d739d7129:554:0df2da8d9b393cc1fcfa
evidence_refs: learning:learn:12859fd9b4f1
created_at: 2026-11-16T00:41:34.665839+08:00
updated_at: 2026-11-16T00:41:34.665839+08:00
---
## Trigger
用户要求把外部框架/文章的概念体系（如记忆分层、决策同步、冲突发现、验收带宽）映射到本系统做现状评估（领先/落后/缺口），且系统存在自述面（architecture_status/config dump）与多个 live 状态工具时

## Discriminator
以外部判据词汇检索 docs/records/files 的 miss 回执自身列出的最近条目标题全用本地项目词汇、无一含外部术语——证明词汇不匹配是该 store 的属性而非查询措辞问题；且早前的自述面（architecture_status）已展示本系统模块/配置命名，翻译词根当时即可得

## Short path
- 确认带入的显式配置要求（一次目录/策略回执即止），不做无条件重复审计
- 把每条外部判据翻译成本系统命名：从自述面 config 键与实现树顶层模块名取词根（memory/lane/coordination 等）
- 行为证据：按判据打对应 live 状态面（决策同步→协调状态投影；验收带宽→队列分诊+实时队列；冲突→lane/S0 面），拿运行时真实数据
- 机制证据：用词根在实现树内做一次 scoped ls/grep，确认机制存在与强度（软告警 vs 硬拦），注释可直接佐证强度语义
- 逐条 verdict，每条断言回指具体回执或代码行；差距按投入产出排序给建议后停止

## Stop conditions
- 每条判据同时有机制面证据（代码/配置行）与行为面证据（live 状态回执）支撑，差距结论可判定
- 出现词汇不匹配信号后，不再用外部同义词对同一 store 重复检索超过一次；不再猜未验证的路径

## Verification
- 终稿中每个『有/无/领先/缺口』断言能回指具体回执或代码行/注释
- live 状态数据与代码声明矛盾时，以 live 运行时回执为准并显式标注矛盾点

## Counterexamples
- 评估对象是文档本身（文档质量/覆盖度评估）——docs 检索就是主 surface，不适用本方法
- 系统的单一自述/状态工具已直接回答该判据——无需进实现树枚举
- 外部框架术语与本系统术语同源（如直接评估某记忆系统时谈『记忆分层』）——直接检索可命中，翻译步骤是多余开销
- 完全陌生的代码库且无任何自述面——无本地命名可翻译，只能退回通用关键词枚举
