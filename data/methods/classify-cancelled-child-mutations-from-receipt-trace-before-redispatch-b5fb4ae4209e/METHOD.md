---
method_id: classify-cancelled-child-mutations-from-receipt-trace-before-redispatch-b5fb4ae4209e
name: classify-cancelled-child-mutations-from-receipt-trace-before-redispatch
description: 后台子代理被父 run 停止级联取消时，先从取消回执自带的工具名轨迹判定变异暴露面：轨迹条数等于回执 tools 计数且全部为 search/read 类 → 零变更，可原样重派，无需工作区取证；轨迹截断或含 edit/execute 则先做 git 取证。重派前把本会话新收到的用户授权/调度决定写入持久 goal checkpoint（中断风险已被同一事件证实），再进入长等待；任务书从 goal 记录点名的 spec 节窄重建，不从记忆泛化。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:648:6918921f64211a9710d2
evidence_refs: learning:learn:8d72174db041
created_at: 2026-10-16T01:15:18.127023+08:00
updated_at: 2026-10-16T01:15:18.127023+08:00
---
## Trigger
后台子代理回执显示 child_state=cancelled（父 run 停止级联，而非子代理自身失败），需要选择恢复路径；或刚收到将约束后续动作的用户决定、且即将进入长时间子代理委派与等待

## Discriminator
取消回执内的工具名轨迹是否完整（轨迹条数 == tools 计数）且全部为只读类（search/read，无 edit/execute）——满足即证明子代理零变更，重派安全且可跳过工作区取证；同时 goal 记录已点名 spec_change_ref 与目标函数，任务书可窄重建

## Short path
- 读取消回执，比对轨迹条数与 tools 计数并检查是否含 edit/execute 类调用；未知量：子代理是否留下部分变更
- 零变更成立 → 按 goal 记录点名的 spec 节与目标模块公开面窄重建任务书，不重新泛化推导整个任务
- 把本会话新增的用户决定（如推送押后条件与执行闸）写入持久 goal checkpoint，然后才重派并进入长等待
- 重派完成时父级只做机械核验（sha256 指纹、定向测试、staged delta 口径），不重走子代理的探索路径
- 若轨迹被截断（tools 计数 > 轨迹条数）或含写类调用 → 先 git status/delta 取证再决定整体重派还是续作

## Stop conditions
- 重派子代理终态 completed 且父级机械核验（指纹一致、定向测试绿、staged 就绪）通过
- 用户决定已持久化（checkpoint 回读确认），且流水线闸门（独立审查 PASS、准入 PASS、ci exit=0）全绿

## Verification
- 仅当回执轨迹条数与 tools 计数一致时才允许下零变更结论；不一致必须以真实 git 状态为权威
- checkpoint 写入后回读 goal 记录，确认授权语义（决定内容 + 执行闸）已落盘
- 重派产物核验用独立机械手段（指纹/测试），不复用子代理自报结论

## Counterexamples
- 轨迹只是前缀截断（如 tools=129 仅列 10 条）时不能推出零变更，必须先做 git delta 取证
- 轨迹含 edit_file/execute_command 时可能存在部分变更，禁止不经取证直接重派
- 取消源于子代理自身错误而非父级停止时，原样重派会复现失败，应先修任务书
- 决定可从上下文廉价恢复、且本会话无任何中断迹象时，持久化步骤是纯延迟
- 无活动 goal/持久存储可用时，退化为依赖续跑 provenance 重建，本方法不适用
