---
method_id: must-exist-term-zero-hit-switch-to-unindexed-ground-truth-6cb544dc95ac
name: must-exist-term-zero-hit-switch-to-unindexed-ground-truth
description: 当内容/元数据搜索对一个『由用户请求本身或已确认事实可推出必然存在』的词返回零命中（或只有 package-lock 之类的无关命中）时，空结果首先是对搜索工具索引覆盖面的证据（如未跟踪文件不入索引），而不是『文档不存在』的证据。此时不要再对同一索引换 pattern/关键词重试，而是改用一次与索引无关的 ground-truth 探针（grep/find/ls、git status --porcelain 含未跟踪文件）重新定位；只有 ground-truth 也为空时才接受『确实不存在』。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:380:189534fc40247cf06c57
evidence_refs: learning:learn:da54470671e9
created_at: 2026-09-28T18:27:34.110858+08:00
updated_at: 2026-09-28T18:27:34.110858+08:00
---
## Trigger
用户消息引用了某个已存在文档的具体章节/内容（如『§6 路径』『先握手』），而对其主题词在对应文件类型（如 *.md）上的索引搜索返回零命中或明显无关命中。

## Discriminator
knowledge-at-time：用户首条消息已引用『§6/握手』，assistant 也已按 codebase-memory 主题发起搜索并自述『那份评估文档还没定位到』——这推出目标文档必然包含字面量 'codebase-memory'；第一次 pattern=*.md 内容搜索零命中与该必然事实矛盾 ⇒ 缺口在索引覆盖（未跟踪文件不被索引），而非文档不存在。

## Short path
- 第一次 must-exist 词零命中后即停止对同一索引换 pattern/关键词重试，改判假设为『索引覆盖缺口』。
- 执行一次与索引无关的定位探针：grep -rl '<term>' docs/ --include='*.md'、ls docs/analysis/，或 git status --porcelain 查未跟踪文件。
- 打开定位到的文档，只读用户实际引用的章节（§1–§6）及关联处置文档的相关行。
- 并行用 ground-truth 命令核掉治理问题（git ls-files、git branch -r --contains <sha>）。
- 两个问题都有当前权威来源支撑后即停止，不再追加确认性读取。

## Stop conditions
- ground-truth 探针找到文档 ⇒ 直接读，不再搜索。
- ground-truth 探针也为空 ⇒ 该词下确实无此 artifact，向用户报告缺失并索取正确标识。
- 用户全部问题已有权威当前来源支撑 ⇒ 停止，不追加『再多确认几个』。

## Verification
- 复述『必然存在』推导：引用用户消息中保证该词必然出现在某文件里的原句（如对 §6 的引用）。
- 确认定位到的文件确实包含该词和用户引用的章节后才从它作答。
- 查看该文件的 VCS 状态（如 '??' 未跟踪）以坐实覆盖缺口解释，并把该搜索边界记录给用户。

## Counterexamples
- 搜索词本身可选或可能改名（找不一定存在的功能名）：零命中可能就是真不存在，应扩宽查询语义或问用户，而非断定索引缺口。
- 索引已返回相关命中、只是想找更优结果：这是相关性/排序问题，不是覆盖缺口，换机制无收益。
- 工具明示 include/exclude 范围且目标在范围内：先怀疑查询写法本身（如 pattern 误写为 '-' 导致 integrity 类无关命中），再谈覆盖。
- 目录体量巨大、grep 代价高：先查工具文档化的排除规则，再决定是否 shell 全扫。
