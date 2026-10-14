---
method_id: entry-artifact-chain-before-corpus-keyword-search-81c999876daf
name: entry-artifact-chain-before-corpus-keyword-search
description: 产出围绕某工作区项目的综述类内容（科普文章/对外介绍/评审材料）时，先用入口 artifact 链解决『项目是什么/往哪去/差距在哪』：仓库根 README → 其显式引用的路线图或 docs 导航 INDEX → 指向的 1-3 份权威文档，而不是对 docs 语料反复换关键词检索。判据：检索回执已显示根 README，或 search 连续 miss 且回执引导列表无变化，即视为通道错配。用户私有参数（如发布渠道）直接问用户，不检索；『未来趋势』属判断型内容，应检索其输入证据（roadmap/gap 文档）而非判断措辞；将发布的经验性数字（库龄/提交数/代码量）须先对权威来源核实再落稿。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:0:d49e778251900f9771ef
evidence_refs: learning:learn:6e7c45479086
created_at: 2026-10-13T22:38:10.682063+08:00
updated_at: 2026-10-13T22:38:10.682063+08:00
---
## Trigger
用户要求基于当前工作区产出项目综述/科普/对外材料，需要项目自述事实与方向性证据（定位、路线图、待攻克技术方向、趋势判断的输入），而入口 artifact（仓库根 README、docs 导航 INDEX）尚未被读取。

## Discriminator
（knowledge-at-time）文件检索回执中已可见仓库根 README.md 这一项目自述入口；或 search_docs 连续 miss 且每次回执返回同一份『最近文档参考引导』、无新增信息——说明概览类问题走错了通道，应转向入口 artifact 而非继续换词检索。另一独立判据：『发布到哪个渠道』是用户私有选择，任何语料检索都无法供给该事实。

## Short path
- 读仓库根 README.md：一次解决『项目是什么』（定位/架构/版本），同时收集正文中显式给出的文档引用（路线图链接、docs/INDEX 等 provenance edge）
- 沿 README 显式引用或读 docs 导航 INDEX（通常很短）：把『路线图/差距/未来方向』映射到 1-3 份权威文档，直接 read_file，不再对 docs 语料换关键词试探
- 关键词/内容检索只用于定位已知会被逐字存储的内容（如竞品差距审计、特定记录）；对『未来趋势』这类判断型内容不搜措辞，而是基于 roadmap/gap 证据自行综合，并在稿中显式标注为推测
- 发布渠道等用户私有参数：直接向用户提问（可先成稿再问），不做语料检索
- 落稿前把每个将发布的经验性断言（库龄、代码量、提交数、评测数字）对权威来源（git log、统计命令）核实；查不到证据的改为标注推测或删除
- 素材可溯源、断言已核实后交付草稿并列出未决用户问题，停止检索

## Stop conditions
- 项目身份与方向性证据（roadmap/gap 权威文档）已读取且成稿断言能指回具名来源
- 同一类问题的检索连续 2 次 miss 且回执引导无新增信息时，停止换词重搜，切换通道（入口 artifact / 导航文件 / 直接问用户）

## Verification
- 成稿中每条事实断言能指回具名文档或命令输出（README、ROADMAP、审计报告、git log）
- 重放检查：入口 artifact 链路应显著少于逐词 corpus 检索的调用数，且不存在对同一未知量的多次变体检索
- 用户私有未知量（渠道）最终由用户回答而非检索结果回答

## Counterexamples
- 仓库无 README/INDEX（裸仓库、纯数据目录）：入口 artifact 不存在，文件名/内容检索就是正确起点
- 目标是散落在日志、讨论、历史记录中的特定事件或报错：入口 artifact 通常不含它，关键词检索才是正道
- 用户只要 README 里一句现成事实：读完 README 即答并停止，不必向 roadmap/审计层展开
- README/文档体系已过期、与代码脱节：须以代码/运行时为准，不能只信入口 artifact 的自述
