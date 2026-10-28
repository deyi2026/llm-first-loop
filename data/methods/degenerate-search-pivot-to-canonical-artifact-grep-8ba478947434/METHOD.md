---
method_id: degenerate-search-pivot-to-canonical-artifact-grep-8ba478947434
name: degenerate-search-pivot-to-canonical-artifact-grep
description: 核实二手转述的软件产品功能断言时，用断言中的精确功能词探测搜索一次、换措辞再搜一次；若两次语义不同的查询返回本质相同的泛化结果集（零功能词命中），判定检索通道对该主题退化，停止改写查询，直接拉取该产品的权威一手工件（官方仓库 raw CHANGELOG.md 等）；大文件下载到本地按精确 token grep，并把营销措辞先归一成官方术语再匹配（防漏配/误配）；工件无日期时，时间性断言如实标注不可核实，不再枚举新闻页/渲染版页面做确认。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:25:38c260350c1e4ddc9c9e
evidence_refs: learning:learn:48e71fbb819c
created_at: 2026-10-16T09:01:07.687739+08:00
updated_at: 2026-10-16T09:01:07.687739+08:00
---
## Trigger
需要核实关于某具名软件产品功能/发布内容的二手转述断言（头条、新闻、教程帖），且通用网页搜索可用、产品存在公开权威发布工件（官方仓库 CHANGELOG.md / 官方 release notes）。

## Discriminator
两次语义显著不同的具体查询（换语言、加精确功能词/命令名）返回本质相同的一般性结果集——同一批入门教程/下载页、零功能词命中。这是通道退化信号而非措辞问题，继续换查询无信息增益；同时产品的官方 raw changelog 可一次拉取全文且可被精确关键词检索（本集两查询返回同一份固定结果集即为此判据）。

## Short path
- 用断言中的精确功能词（命令名/flag/功能名）做一次探测搜索，记录结果集。
- 换语言或措辞做第二次搜索；若结果集与第一次本质相同且无功能词命中，判定通道退化，剪掉整个关键词检索分支。
- 直接拉取产品权威一手工件（官方仓库 raw CHANGELOG.md）一次获取全文，同时从其结构（如仅版本号无日期）判断哪些子断言在此源可解。
- 大文件下载到本地按精确 token grep；二手营销措辞先归一为官方术语（如『保存环境』→saved/remote environment、『嵌套会话』→nested subagents）再匹配，避免误配『deeply nested』类噪声。
- 逐条断言映射官方条目，给出属实/术语漂移/无法核实判定并引用版本号；时间性子断言若工件无日期信息，一次确认后即报告不可核实并停止。

## Stop conditions
- 所有待核断言均已映射到权威工件的具体条目（可引用版本号/条目原文）或确认在该工件中缺席。
- 时间/版本归属类子断言在权威工件中无信息（如 changelog 仅版本号无日期）→ 如实标注不可核实，不再枚举 newsroom/渲染版 changelog 页试图补齐。

## Verification
- 每条判定引用权威工件原文片段与版本号，且命中词与官方术语一致（非二手转述词）。
- 渲染版页面（官网 /changelog、docs release notes）抽取退化（仅剩导航壳/页脚）时不作为证据源，以 raw 仓库文件为准。

## Counterexamples
- 两次查询返回不同结果集且含功能词命中（通道健康）→ 正常精化查询即可，无需跳一手源。
- 闭源产品无公开仓库/changelog，权威工件是厂商博客/帮助中心 → pivot 目标不同，本地 grep 流程可能不适用。
- 断言核心是发布日期而 changelog 无日期 → 本地 grep 解决不了该未知量，最多一次尝试带日期的 release notes，否则报告不可核实。
- 工件很小或断言已能被首次探测搜索的一手结果直接覆盖 → 直接阅读即可，无需下载本地 grep。
