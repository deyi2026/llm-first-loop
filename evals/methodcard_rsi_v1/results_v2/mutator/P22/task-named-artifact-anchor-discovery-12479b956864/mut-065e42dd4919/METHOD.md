---
method_id: task-named-artifact-anchor-discovery-12479b956864
name: task-named-artifact-anchor-discovery
description: 实现前核对'任务点名的具体工件'（端点/前端/V版本测试）时，用工件名/版本token做首选发现键，而非领域概念token：概念键（通道/桶名）会跨engine/queue/多测试全库扇出，对'尚未实现的交付物'关键词的搜索注定miss。命中文件的头注释即provenance edge（端点+设计文档路径），沿它一跳拿权威结论，再定向读实现面。与git-delta重建剩余工作的续跑法不同，本方法解决的是发现入口的选键问题。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1750:ca0536ebd2d1d0e2b16e
evidence_refs: learning:learn:580b1af9efa2
created_at: 2026-10-14T14:00:15.318464+08:00
updated_at: 2026-10-14T14:00:15.318464+08:00
---
## Trigger
任务或用户已批准的计划点名了具体版本化工件（功能代号/版本号/组件名，如某里程碑面板端点、某V版本契约测试），需要在动手改之前核对这些工件的当前事实。

## Discriminator
任务文本自带的工件名/版本token（如M1c、V3、面板组件名）在仓库中近乎唯一命中；而领域概念token（通道/桶名）首轮搜索结果即显示跨engine/queue/多测试文件扇出；且近期git log提交信息常点名承载结论的分析文档——这些零成本已见事实足以把发现键从'全库概念搜索'缩为'点名工件+其头注释引用链'。

## Short path
- 用工件名/版本token搜索或定向find（前端src目录、tests具体子目录）定位点名的面板组件与契约测试，各一跳
- 读命中文件头注释，取得端点、数据源、设计依据文档路径等显式provenance edge
- 沿头注释点名的分析文档读结论小节（或文档内grep成因关键词），拿交付物所需权威口径（如结构性零的两桶成因）
- 只对实现面做一次定向grep/read（限定子路径，勿在含node_modules/dist的树上全库grep致超时）确认现有代码形态
- 实现后跑点名契约测试与相关回归，通过即停；不再对概念token做全库枚举或换措辞重搜

## Stop conditions
- 点名的端点/前端/测试三面事实均从命中文件及其引用的权威文档读到且口径一致
- 对'尚未实现的交付物关键词'的文档/代码搜索首次miss即停（必然miss不构成信息），改走git log/点名文档
- 概念token搜索结果跨多层扇出且不再产生与点名工件相关的新信息时停止枚举

- Verification 未逐条通过前不结案（覆盖全部 3 条验证条目）

## Verification
- 命中文件头注释中的端点/文档路径与实际后端路由、所读文档一致（provenance闭合）
- 新增标注内容逐条可回溯到权威文档结论小节
- 点名契约测试通过并覆盖新增字段

## Counterexamples
- 任务只有概念性目标（如'降低插话时延'）未点名任何工件：无名称锚点，应走目录/概念发现
- 点名token歧义（V1/V2/V3并存且未指明当前版本）：需先消歧，不能直接读第一个命中
- 工件刚在本会话读过且上下文仍新鲜：重读即浪费（本集明确声明上下文未实读，重读才正当）
- 头注释引用的文档已迁移/过时（edge断裂）：此时才回落到目录与搜索式发现
