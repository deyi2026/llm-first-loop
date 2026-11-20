---
method_id: ledger-on-repeat-guard-then-thicken-waits-until-terminal-6f243f70829a
name: ledger-on-repeat-guard-then-thicken-waits-until-terminal
description: 任务书明令同一 Run 连续轮询受管子任务到真实终态、waiting_protocol 也授权『pending 才继续查询或等待』时，防重复护栏报『同一精确调用已第 3 次成功』说的是语法重复而非信息耗尽：非终态回执仍携带新状态（remaining_seconds 单调递减）。正确响应分两步：先按护栏自带指令一次性把已核事实、引用、未决量与预算中止条件记入账本；随后继续轮询但加厚每次调用承载的墙钟——插入普通等待或增大 wait_seconds，使后续调用不再逐字相同。终态一旦出现立即停止，核对终态回执候选哈希与受理回执一致后才收口报告。
aliases: 同一个查询发了三遍的提醒, 等审查结果时拉长每次间隔, pending 期间少发空转调用, 防重复提示不是让你停
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:913:a955ad401823c0a00033
evidence_refs: learning:learn:e4bb136766df
created_at: 2026-11-19T20:31:41.497807+08:00
updated_at: 2026-11-19T20:31:41.497807+08:00
---
## Trigger
收到 waiting_protocol 授权连续轮询（或任务书明令『轮询到真实终态』）后处于非终态等待循环中，工具回执附带 repeat_guard：该精确调用本 run 已第 3 次成功执行，提示先记账、勿继续重复探索。

## Discriminator
两条当时可见事实共同判定这是收敛等待而非探索性重复：(a) 非终态回执携带推进中的新状态——remaining_seconds 单调递减、qualification 仍 pending，每次调用都在逼近同一未知量（是否终态）；(b) 受理回执 waiting_protocol 明文允许 pending 时继续查询或等待。护栏计数的是调用文本相同，不代表信息已尽。

## Short path
- 先分类：本次循环是否由任务书要求或 waiting_protocol 授权到终态？是→收敛等待，进入下一步；否→探索性重复，换分支，本方法不适用。
- 按护栏指令，一次性把已核事实+source_refs+未决量+预算中止条件写入 task_state 账本（一条记录完成）。
- 继续轮询但加厚等待：在两次查询间插入普通等待，或增大查询自带的 wait_seconds，使每次调用承载更多审查墙钟且不再逐字相同。
- 回执出现真实终态（PASS/FAIL/拒绝）立即停止轮询；核对终态回执候选哈希与受理回执一致，再 checkpoint 并如实报告。

## Stop conditions
- qualification 返回非 pending 终态（PASS/FAIL/拒绝）——轮询使命完成。
- 达到任务书/协调员的墙钟预算仍 running：checkpoint 阻断并如实报告，子任务继续在宿主侧跑，不自述通过。
- 回执不再携带新状态（remaining 不减或内容不变）：视为真重复，停止该手段并另寻信息源。

## Verification
- 终态回执与受理回执的候选内容哈希逐字一致。
- 轮询序列的 remaining_seconds 单调递减，证明每次调用携带新信息。
- 账本记录含可回溯引用（审查子任务、内容 sha、git HEAD、共享账本版本），未决与中止条件明确。

## Counterexamples
- 护栏触发于真正的探索性重复（同一搜索/读取不可能有新状态）：该做的是换假设/换工具，记账继续只会原地打转。
- 一次性准入资格已签发且冻结窗口未消费、账本写入物理落在被绑 workdir：立即记账会改切片外摘要作废资格，应推迟或写到绑定集之外（冻结窗口方法管辖）。
- waiting_protocol 并列了完成唤醒绑定且任务未禁止：优先绑完成唤醒，仅在任务明令轮询或绑定被参数约束拒绝时退回本方法。
