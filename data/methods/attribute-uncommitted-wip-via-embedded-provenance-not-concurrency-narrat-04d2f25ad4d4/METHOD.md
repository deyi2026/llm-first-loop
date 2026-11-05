---
method_id: attribute-uncommitted-wip-via-embedded-provenance-not-concurrency-narrat-04d2f25ad4d4
name: attribute-uncommitted-wip-via-embedded-provenance-not-concurrency-narrative
description: 共享工作区里发现未提交改动时，『别的会话的并发 WIP』是需要证据的归属断言而非默认解释：untracked 生成物通常在自身元数据（front matter 的 source_episode_refs/生成者戳）里写明作者，抽样读卡即可批量归属；tracked 修改用带 session ID 的事件流按路径+时间窗归属，再对照 git log 与审查回执识别『已过审未落库』等悬空状态。计数随时间漂移，报告以带时刻的当前实测为准；归属不明就明说未知，不用排除法硬编并发叙事。
aliases: 脏文件是不是别的会话写的, 没提交的改动先查写者再说, 事件流session id定位改动来源, 已过审没落库的改动怎么识别, 把并发WIP当默认解释的坑
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:1075:bfee161ce9888d3649eb
evidence_refs: learning:learn:d403e54b1829
created_at: 2026-11-05T17:33:44.830388+08:00
updated_at: 2026-11-05T17:33:44.830388+08:00
---
## Trigger
共享/多会话工作区出现未提交改动（tracked 修改与 untracked 新文件混合），需要向用户或自己解释其归属与状态，或即将据此决定提交/清理/等待；上下文存在并发会话，容易把改动默认解释为『别人的 WIP』。

## Discriminator
工件自带归属元数据：untracked 生成物（知识卡/报告/流水线产物）的 front matter 内嵌 source_episode_refs 或生成者标识，一次抽样读即可把这批归到具体 session；tracked 修改在带 session ID 的 action/event 流里按路径+时间窗可查到写者。拿到任一证据之前，任何并发归属都只是假设。

## Short path
- git status --porcelain 取完整清单并记录观测时刻；未知量：构成（tracked 修改 vs untracked 聚类）。
- untracked 按目录聚类，抽读 1–2 个工件的元数据头，用内嵌 source/episode 字段归属到 session；未知量：untracked 是谁的。
- tracked 修改在事件流/action 日志按路径过滤，读 session ID 与时间窗；未知量：谁改的、改动处于什么状态。
- 对照 git log 最后提交点与审查回执，识别『已过审未落库』『待入库管道堆积』等悬空状态。
- 按归属+状态汇报风险，把提交/保持等处置作为有界选项交用户；无法归属的残余明标未知。

## Stop conditions
- 每条 dirty 路径有明确归属（session ID 或内嵌 provenance）且状态可分类（已审未提交/待管道入库/外部 WIP）。
- 内嵌 provenance 与事件流均覆盖不到的条目：停止归因枚举，标注归属未知并给出下一跳（问用户/查锁新鲜度）。

## Verification
- 抽样归属结论与事件流 session ID 交叉一致；『别人的』部分必须有不同 session ID 的正面证据，不能用排除法。
- 报告计数带测量时刻，可由当前 porcelain 复现；不与旧口径数字强行调和。

## Counterexamples
- 工件不带内嵌 provenance 且事件流不覆盖（人工编辑、外部工具写入）：改用 mtime/锁新鲜度与用户确认，不硬读元数据。
- 单会话独占工作区：归属平凡，直接分析改动内容即可，无需归属流程。
- 工件从别处拷贝、front matter 指向旧作者：内嵌字段只当线索，以事件流实际写者为准。
