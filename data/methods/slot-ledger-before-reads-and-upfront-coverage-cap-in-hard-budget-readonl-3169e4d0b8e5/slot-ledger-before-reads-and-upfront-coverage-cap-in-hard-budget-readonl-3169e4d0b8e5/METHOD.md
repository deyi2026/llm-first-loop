---
method_id: slot-ledger-before-reads-and-upfront-coverage-cap-in-hard-budget-readonl-3169e4d0b8e5
name: slot-ledger-before-reads-and-upfront-coverage-cap-in-hard-budget-readonly-review
description: 硬性只读工具预算的审查/取证任务，任务书点名列出必须核验的工件时：第一次回执（冻结SHA+diffstat枚举全部改动路径）后立刻做读取排程——剩余槽位×具名工件逐槽预分配，每槽只花在尚未覆盖的账面条目上，优先合并式调用（多pathspec diff、合并grep）一槽覆盖一簇。凡事实在已具名的冻结工件路径上可直接读取，绝不把该未知量路由到会话证据库关键词搜索：该通道只能返回重复或空，本集一次零命中查询即耗掉1/6预算，最终三个具名文档无槽可读，verdict被迫以覆盖缺口降级。预算<工件数时把未覆盖集写进结论头部作显式上限，而非收尾补报。
aliases: 审查额度不够读完清单怎么办, 调用次数用满了还有文件没看, 查询扑空浪费一次调用, 硬上限任务的读取顺序怎么排, 报告里承认没查完的范围, 审前先排要读哪些文件
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d5ff72d8-9357-4587-9adb-20bdfc2b73ef:0:0e3a6e6db939b9b7cde0
evidence_refs: learning:learn:b8714391e7b4
created_at: 2026-11-17T17:54:23.853151+08:00
updated_at: 2026-11-17T17:54:23.853151+08:00
---
## Trigger
带硬性小工具预算（如最多6次）的只读审查/取证任务，任务书点名必核工件与清单项，且首次回执（git facts+diffstat）已枚举全部改动路径。

## Discriminator
预算N与具名证据集K在任何内容读取前均已可算（预算来自任务书，工件清单来自diffstat+任务书）。每个候选调用先问：它能否带回'任何尚未覆盖的具名证据'？事实若在已具名冻结工件上可直接读取、或已在先前回执中，则绕道证据库关键词查询是可预测零增益槽——本集第3槽store零命中正是该判据当时即可排除的动作，收尾时三个具名文档无槽可读，verdict以P2覆盖缺口降级REVISE。

## Short path
- 第1槽：冻结SHA+git facts+diffstat；据diffstat与任务书枚举具名证据工件清单（本集11路径含三份证据文档）
- 排程：剩余N-1槽对K个工件逐槽预分配，写明哪些工件'计划内不覆盖'
- 每槽对应一个未覆盖账面条目；用合并式调用覆盖簇（多pathspec diff一次覆盖全部改动、一次合并grep确认负测断言簇）
- 冻结工件上可直读的事实绝不走证据库关键词搜索通道
- 槽尽即收：verdict只引用持有回执的file:line，头部声明未覆盖工件作为coverage cap

## Stop conditions
- 全部具名工件均有回执覆盖 → 正常verdict
- 预算耗尽 → verdict头部显式列出未覆盖工件（coverage cap），不冒认全量审查
- 某槽返回零新增具名证据（如store零命中）→ 该通道在本任务内不再复用

## Verification
- verdict每条file:line引用可对应trace中的一条回执；无回执引用不得出现
- verdict头部含覆盖账：已覆盖 vs 声明未覆盖
- trace中不存在预分类为零增益通道的调用

## Counterexamples
- 证据库是该工件唯一访问通道（沙箱禁止直读冻结工件）时，store查询就是窄边，不属浪费
- 先前回执覆盖不完整且diff hunk缺判断所需上下文时，正确的槽位花费是对工件直接span读（先读工件，不是先搜库）
- 预算≥工件数且有富余时，排程是仪式开销，跳过；只需避免对已持有回执的字面重读
- 无预算约束的普通开发/实现任务不适用
