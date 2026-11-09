---
method_id: post-gate-closure-gap-classify-defer-or-regate-86fe245a36fc
name: post-gate-closure-gap-classify-defer-or-regate
description: 已过全量门禁、审查链已收敛的变更批次处于收口合并期时，新发现的边缘输入缺口不能当作顺手 side-edit 拼进当前树：先二分类——审批增量的主路径契约内缺陷→有意重开（提交修复+重跑受影响门禁+新一轮审查+更新回执）；契约外异形输入形态→回执 known-gap 挂账、指向后续批次。本集收口期自行给 push 守卫补 --repo 解析，原始值直喂 ls-remote 构成选项注入，R9 判 P1 后整段撤销改 fail-closed，多付一轮审查与约 40 分钟。合并候选 tree 必须始终等于已门禁 commit。
aliases: 收口期别顺手加修复, 门禁过了就冻结工作树, 合并前发现小缺口挂账还是重跑CI, 过了全量测试又想改代码, 边缘输入缺口延后到下一批
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:7086:1c72361419a2561ca86e
evidence_refs: learning:learn:0b5a7667d01e
created_at: 2026-11-09T14:56:25.310214+08:00
updated_at: 2026-11-09T14:56:25.310214+08:00
---
## Trigger
变更批次的全量门禁/审查准入回执已绑定具体 commit（或门禁正在跑且回执明示冻结工作树），批次进入收口合并期；此时通过顺手探测又发现正在交付的代码还有一个未覆盖的边缘输入形态或小缺陷，产生『现在就修掉』的冲动，且该修复并不在审批增量范围内

## Discriminator
两条当时已在手的事实即可裁决：①门禁/准入回执绑定特定 HEAD——git status 一旦出现源码 M，回执与合并候选即脱钩，且收口清单（回执/合并/部署/推送）里不含任何代码改动步骤；②同批审查链已把同等级的兄弟边缘形态缺口分级挂账延后（删除 refspec、--git-dir 等）——新发现的异形缺口属同一等级，也应延后；只有『审批增量声称判定的主路径输入被误判』才构成重开门禁的理由

## Short path
- 发现新缺口时先核对收口状态：门禁/准入回执绑定的 commit 与当前 tree 是否仍一致（git status / rev-parse 对照 gated HEAD），而不是先动手修
- 二分类：缺口在审批增量主路径契约内（主流输入被判错）→ 有意重开：提交修复、重跑受影响门禁、走新一轮审查、更新回执；契约外异形形态 → 回执写 known-gap 条目并指向后续批次，当前树恢复到 gated HEAD
- 合并队列提交前，工作树必须干净或与重新门禁后的新 commit 一致；收口期不得携带未提交源码改动进入合并流程
- 若确需在守卫中处理其值会流入下游 git/shell 调用的异形 flag：优先 presence 检测 + fail-closed 拒绝并报因，不解析、不透传原始值
- 收口按 gated HEAD 执行合并，回执披露全部延后缺口及去向，停止

## Stop conditions
- 合并候选 tree 与已通过门禁/审查准入的 commit 完全一致（status 干净或 sha 相符）
- 所有新发现缺口均已二选一落账：随重开门禁修复闭环，或已写入回执 known-gap 并指向后续批次

## Verification
- git status 与 rev-parse HEAD 对照门禁回执中的 HEAD sha 及审查准入 candidate sha，确认无脱钩
- 回执中可检索到该缺口条目及其处置（fixed-with-regate / deferred+去向）
- 走 fail-closed 路线时，用应拦输入实测确认异形 flag 形态被拒且报因正确

## Counterexamples
- 缺口破坏的是增量本身的主路径契约（如守卫对主流『push 远端 分支』形态误判）——延后会合并一个明知坏掉的功能，必须当场修复并重开门禁，不能挂账
- 门禁尚未开跑的正常开发期发现缺口——直接在本批修掉即可，冻结纪律只适用于门禁后收口期
- 纯文档/回执增补、无可执行行为变化——不触发代码门禁重跑，收口期写入即可
