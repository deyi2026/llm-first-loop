---
method_id: plan-stage-directive-resolve-via-dated-doc-namespace-first-71417927e3b9
name: plan-stage-directive-resolve-via-dated-doc-namespace-first
description: 指令以计划阶段标签（如 S1.5/存量筛/实例池/配对/41卡）指代工作项时，这些标签的权威定义与当前状态存于治理文档命名空间（docs/ 的 DESIGN-/ASSESS-/ANALYSIS-YYYYMMDD-slug 约定），而非 evals/results 运行产物目录。先拆词枚举该命名空间文件名（或把 grep 限定在 docs/），读设计与状态盘点文档锚定各建议项现状，再沿文档内引用的精确产物路径取数执行。避免：整句检索未命中后跳到整库文件名搜索；cd 进数据子树后做相对 grep（结构性够不到 docs/）；用阶段词全树 grep（命中几十张生成 METHOD.md 噪声）；宽枚举直到工具超时。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:596:cd61eefa4bcc3be897cc
evidence_refs: learning:learn:00df7126b8f6
created_at: 2026-10-21T08:36:15.973012+08:00
updated_at: 2026-10-21T08:36:15.973012+08:00
---
## Trigger
用户指令（如『按建议执行』）用计划/流程阶段标签或盘点口径词指代多个工作项，且仓库存在带日期+体裁前缀的治理文档目录（Genre-YYYYMMDD-slug 命名的 docs/）

## Discriminator
search_docs 对指令原句未命中，但回执已展示 docs/ 近文档清单及其 Genre-YYYYMMDD-slug 命名约定；指令词条是计划阶段词，而 evals/results 文件名是 heldout/pool/calls 等运行产物词——两类词表不相交，阶段词只可能出现在文档 slug 中，这一事实在第一次未命中时就已可见

## Short path
- 把指令拆成特征词（阶段号 S1.5、slug 词 prefilter/item-pool/funnel），不用整句做检索
- 枚举 docs/ 文件名按 slug 匹配，或把 grep 限定在 docs/*.md；不进入 evals/results 子树后再做相对检索
- 读命中的设计文档（各阶段定义、判据、预注册失败标签）与状态盘点文档（各线现有量、阻断标签、41 卡配对可行性结论）
- 把每条建议映射到文档化状态：已完成→只报增量；已阻断→引用既有失败标签，不重推导；真正新增项→沿文档内引用的精确路径（冻结 jsonl、usage 台账）取数执行
- 确认当前 cwd 未把后续检索作用域锁死在数据子树内

## Stop conditions
- 每条指令项都已映射到权威文档裁决或已执行增量，且引用路径与文档一致
- 文档命名空间枚举确无对应词条（全新工作）→停止搜索，转立规格或问用户，不再换词考古

## Verification
- 最终报告每条结论可回指具名文档及其引用的冻结产物路径/sha
- 不与文档已记录的失败标签冲突（已标 BLOCKED 的配对不得当作可跑项）
- 发起任何 grep/search 前确认作用域覆盖 docs/（当前目录不是 evals/results 子树）

## Counterexamples
- 标签实际指向代码符号/配置键/字段名时，代码与数据检索才对，文档命名空间无关
- docs/ 落后于更新的结果文件（文档 mtime 早于产物）时文档优先会误导，须先比新鲜度再采信
- 建议项从未被任何文档记录（全新工作）时，枚举命名空间只会空转，正确未知量是先写规格
- 小型仓库无命名空间约定且全库枚举成本极低时，本方法无增益
