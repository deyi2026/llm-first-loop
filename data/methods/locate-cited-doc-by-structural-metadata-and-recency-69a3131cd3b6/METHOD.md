---
method_id: locate-cited-doc-by-structural-metadata-and-recency-69a3131cd3b6
name: locate-cited-doc-by-structural-metadata-and-recency
description: 当用户消息用可机械验证的结构元数据（精确行数、§编号锚点、DESIGN/REVIEW 成对命名、近期修改）指向仓库内一份散文文档时，用一次 mtime 排序的 docs 目录列举加 wc -l/标题 grep 两步完成定位与确证，而不是拿文档内容关键词做全库 content 扫描——当检索索引不覆盖 prose 文档时，这类扫描只会返回代码噪声或假阴性（本集 '注入防护' 明确存在于目标文档却报无匹配）。定位后只读被引用的锚点章节；对随附的代码事实主张另用窄符号检索逐条核验，两条通道不混用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:0:d371751429c53d91dddc
evidence_refs: learning:learn:17aa51e9245a
created_at: 2026-10-09T10:49:42.726783+08:00
updated_at: 2026-10-09T10:49:42.726783+08:00
---
## Trigger
用户消息引用仓库内某份文档并带有结构 pin：精确行数（如"693 行"）、§编号锚点、成对 review 报告、DESIGN/REVIEW 式命名；需要定位、核对并修订该文档，且初始 search/search_docs 未直接命中目标。

## Discriminator
动作前已可见：用户给出的行数与全部 § 锚点可作确定性指纹（693 行 + §8.3/§9.1/§10.2/§12.3/§13）；search_docs miss 回执证明 docs/ 目录存在且其索引/引导不含目标，说明该通道找不到它，而文件系统元数据列举一步可达。

## Short path
- 对 docs/ 做 mtime 排序列举，取最近的 DESIGN/REVIEW 候选对——解决'哪个文件'
- wc -l + 标题 grep 顶层候选：行数与用户所述精确相等且全部 § 锚点在场 ⇒ 目标确证，发现阶段停止
- 只读被引用锚点章节与成对 REVIEW 全文，建立修订落点
- 对用户声称的代码事实做窄符号检索（如 _next_id、run_skill_load 的 body 提取），只读命中文件的相关行段核验
- 落盘修订，用行数增量与锚点 grep 验证

## Stop conditions
- 候选文档 wc -l 与用户陈述的行数精确一致，且标题表覆盖其引用的每个 § 锚点
- 代码事实主张在与检索回执一致的文件行段得到原文确认或证伪

## Verification
- wc -l 输出数字与用户消息中的行数陈述相等
- grep 标题包含用户引用的全部 § 锚点
- 修订后 wc -l 增量与修订条目数相符，原有锚点仍可寻址

## Counterexamples
- 用户只引用行为或符号、无任何结构元数据（无行数、无 § 锚点、无文档命名）：应直接窄符号检索定位代码事实，目录列举无从下手
- 目标不在仓库文件系统、仅在对话中引用：元数据探针为空，需从消息文本本身重构
- 仓库无 docs/ 惯例或存在大量同形文档使 recency 无法判别：退回内容检索
- 目标 artifact 是代码而非散文文档：行数与命名惯例不是可靠指纹，应走定义面+调用点查证
