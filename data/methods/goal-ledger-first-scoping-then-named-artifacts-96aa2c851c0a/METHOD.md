---
method_id: goal-ledger-first-scoping-then-named-artifacts-96aa2c851c0a
name: goal-ledger-first-scoping-then-named-artifacts
description: 接手式缩写指令（如 'p0，p2，p3'）且各项指向已被 goal/task 跟踪的交付物时，不要用关键词搜索+目录枚举去推断『现状』。先对每个被引用项查一次 tracker 状态/checkpoints：一次查询即给出权威的 done/remaining 账本，并点名该读哪些工件；文档只补细节。与无账本时的 named-provenance/git-delta 发现法互补。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1378:1b0ea804f809e949d519
evidence_refs: learning:learn:1229a88a8918
created_at: 2026-10-14T12:13:36.090346+08:00
updated_at: 2026-10-14T12:13:36.090346+08:00
---
## Trigger
接手式缩写/转交指令（如 'p0，p2，p3'），其中每个条目映射到一个已被跟踪的 goal/候选/交付物，而其当前状态（待实施 vs 已交付待回填 vs 已闭合）未知

## Discriminator
条目所指对象在派发时即可知存在 goal/task 台账记录（指令措辞本身引用『候选 3』这类被跟踪编号，且会话具备 goal 查询能力）——一次 status 查询就能把『还剩什么』从全库文档枚举级不确定性缩到台账点名的一两份工件；该事实无需任何后续读取即可使用

## Short path
- 对每个条目先查其指代 goal 的 status/checkpoints，解决未知量『这项工作是实施还是收尾』（如 status=complete+交付闭合时间戳 → 剩余仅回填/截图/验证）
- 只读台账/目标名所点名工件的关键小节（验收门、实施记录），定位回填缺口；不做全目录枚举，不按上下两半拆读同一文档
- 对用户声明跳过的条目（如 P1），读台账指向的权威小节（交付报告 §5.2 实施方回填段）确认确已完成，再纳入收口结论
- 执行剩余工作，最终按『tracker 状态 × 工件小节交叉一致』逐项核对后停止

## Stop conditions
- 每个条目已化简为明确剩余任务清单，且待读工件均被台账点名 → 停止一切宽发现
- search 未命中的回执已列出点名参考时，不再换措辞重查，改走台账/点名文档
- 被跳过/视为已完成的条目已找到至少一条权威闭合记录 → 不再追查

## Verification
- 最终对每项状态的断言同时引用 tracker status/时间戳与对应工件小节作双证据
- 台账与工件不一致时（如文档缺实施记录），先以 git/报告工件量化 delta 再裁决，不单信一侧

## Counterexamples
- 无 tracker/goal 台账（新项目或未记录工作）→ 无状态可查，应回到 named-provenance/git-delta 式发现，本方法不适用
- 台账 stale（实施者未回填状态或未闭合 goal）→ tracker-first 会误导，必须以 git log/报告工件交叉核对
- 任务目标就是文档内容本身（如『总结六桶口径』）而非状态厘清 → 台账查询无信息量，读文档即主体工作
