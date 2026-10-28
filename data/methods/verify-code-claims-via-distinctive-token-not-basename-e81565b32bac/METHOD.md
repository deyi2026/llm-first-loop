---
method_id: verify-code-claims-via-distinctive-token-not-basename-e81565b32bac
name: verify-code-claims-via-distinctive-token-not-basename
description: 复核具体代码事实断言（file:line+片段）时，断言文本里已含近乎唯一的 token（contextvar 名、错误码字符串等）；用它做内容搜索可一步同时定位 live 文件与行号。按文件 basename 搜索在含快照/worktree/vendor 全量拷贝的仓库里只会枚举出截断的同名歧义结果，top 命中常被快照前缀占据而翻不到 live 文件。命中被重复树前缀淹没时，应从任一 live 命中或一次布局确认（ls/git）推导 live 路径后直接读取原文，而不是分页枚举或把快照内容当成现状真值。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:68:36701a4ccaf3dca3af9d
evidence_refs: learning:learn:3303655b95a0
created_at: 2026-10-16T09:11:48.764717+08:00
updated_at: 2026-10-16T09:11:48.764717+08:00
---
## Trigger
在含重复检出树（发布快照、任务 worktree、vendor 全量拷贝）的仓库中，需要复核一条具体代码事实断言（file:line + 片段/标识符），或文件名搜索返回大量同名且截断结果时

## Discriminator
断言引用的片段中是否含有项目内近乎唯一的标识符/字面量（有则应以其为内容搜索键）；以及文件名搜索回执是否截断且被快照前缀占据（是则 basename 无区分度，继续枚举无信息）

## Short path
- 从断言文本提取最独特的 token（标识符/字符串字面量），做内容搜索而非按 basename 搜文件名
- 命中只落 live 树且行内容逐字一致 → 直接 read 该处上下文确认语义，该项复核即完成
- 命中混有快照/worktree 前缀 → 用任一 live 命中或一次 ls/git 确认 live 路径布局，直接读 live 路径，不分页枚举搜索结果
- token 零命中或行内容不符 → 判定断言过期或已改名，先重定位当前机制再继续设计
- 全部引用在 live 树原文级确认后停止取证

## Stop conditions
- 断言中每处 file:line 与语义引用都在 live 树取得逐字一致且上下文语义吻合的确认
- 唯一 token 搜索零命中且排除改名可能后，判定断言过期，停止沿旧事实继续设计

## Verification
- 最终引用的命中路径不带快照/worktree/vendor 前缀（确为 live 树）
- 引用行内容与断言逐字一致，且读到的上下文支持断言的语义解释，而非仅行号巧合

## Counterexamples
- 断言不含任何独特 token（仅'某配置文件设了 X'）→ filename/目录搜索才是合理起点
- token 是高频泛用词、命中数百条 → 唯一 token 法退化，需换组合词或其他定位手段
- 审查对象本身就是历史快照/发布版本 → 必须读快照，live 树优先纪律不适用
- 仓库无重复树且 basename 唯一 → 直接按文件名定位更省一次内容搜索
