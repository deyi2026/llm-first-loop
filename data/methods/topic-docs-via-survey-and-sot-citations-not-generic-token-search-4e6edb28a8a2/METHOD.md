---
method_id: topic-docs-via-survey-and-sot-citations-not-generic-token-search-4e6edb28a8a2
name: topic-docs-via-survey-and-sot-citations-not-generic-token-search
description: 在含 vendored 依赖树（.venv site-packages）与 .releases 快照镜像的仓库里，为对比/评析任务收集某主题的仓库侧文档与事实时，用通用技术名词（harness、version、model 等）做全局文件名检索会结构性产出噪声（本集一次检索 30/30、另一次过半命中均为依赖/镜像副本）。改走两条已存在的边：该主题最新的带日期综述/评审文档（其引用图即主题文档集索引），以及已读 SoT 文档正文中点名的交叉引用；数量类事实由生产者命令一次产出。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:13:e4e03bbf5b8b9c7efe69
evidence_refs: learning:learn:d09acd9141cf
created_at: 2026-10-21T07:35:08.478260+08:00
updated_at: 2026-10-21T07:35:08.478260+08:00
---
## Trigger
需要在当前仓库收集某主题的文档与机制事实（如对比外部系统 vs 本仓系统），而候选检索词只是通用技术名词，且仓库含 .venv/site-packages、.releases 等会吞噬命中的目录

## Discriminator
早前回执里已出现该主题的带日期综述/评审文档名（文件名含主题词+年份的 landscape/review 类），且已读 SoT 文档正文点名引用了后续所需的配套文档；或一次试探性全局检索的回执显示命中大部分落在 site-packages/.releases 路径下——回执本身证明该 token 在此树中无判别力

## Short path
- 先读最早回执已命中的该主题带日期综述/评审文档，把其引用清单当作主题文档集的索引
- 沿已读 SoT 文档正文中点名的交叉引用（具体 file/doc 名）定点读取，不回到通用词文件名检索
- 数量/统计类事实（行数、卡数、目录数）用一次生产者命令在活树上产出可引用证据
- 外部侧声明走其一手来源核验，与仓库侧并行推进，不用仓库内检索替代
- 汇总对比时显式检查最新综述的收录缺口与既有评审结论的时效（新外部证据是否晚于评审依据）

## Stop conditions
- 每个对比维度的两侧事实均有权威来源支撑（SoT 文档 / 生产者命令回执 / 一手外部来源）
- 综述收录缺口与结论时效冲突已显式标注，或确认不存在

## Verification
- 复查通用词检索回执：命中是否几乎全为 site-packages/.releases 副本（若是则该发现通道已被证伪，不再重复尝试）
- 对比表中每个本仓侧数字都能指到一次命令回执或 SoT 文档的具体位置

## Counterexamples
- 主题在本仓无任何综述/SoT 文档（绿地主题）——此时 docs/ 范围检索或目录枚举是正当起点
- 检索词本身是稀有精确 token（完整文档 ID、专名）——文件名检索一次即中，无需换通道
- 目标事实恰好在依赖树内部（核验已装包的真实 API/版本）——site-packages 命中是目标而非噪声
- 检索工具已内置排除 venv/镜像目录时，通用词命中可能仍有判别力，先看回执再定
