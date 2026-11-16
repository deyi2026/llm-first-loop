---
method_id: countdown-scheduled-polling-and-channel-alternation-on-duplicate-guard-fe4ada146562
name: countdown-scheduled-polling-and-channel-alternation-on-duplicate-guard
description: 轮询受管异步子代理/审查闸时，回执自带的量化预算就是排程依据：elapsed=deadline−remaining_seconds，与 estimated_seconds 比较决定本轮是再等还是再查；同一精确 status 调用连发别超过约2次，一旦命中 run 级重复守卫，守卫文本已指明出路——立即写 task_state 账本（已核事实+未决+下一步），再按 waiting_protocol 换通道（普通 wait 返回后立即查 status），既不第4次原样重发，也不弃检或重启审查。终态到手后仍须指纹绑定再引用。
aliases: status查了几次还pending怎么办, 等子代理出结果别反复发一样的调用, 用剩余秒数安排下次查询, 轮询被警告后先记账再等, 按预估时长等审查终态
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a43dc767-17c2-429a-82f3-1dd9d4aa5558:317:ab60fa439210b634b0b3
evidence_refs: learning:learn:4742ff0a50f3
created_at: 2026-11-15T23:13:34.064477+08:00
updated_at: 2026-11-15T23:13:34.064477+08:00
---
## Trigger
受管异步子代理/准入闸已启动，回执含 waiting_protocol 与量化预算字段（estimated_seconds/deadline/remaining_seconds），任务要求轮询到真实终态；运行环境存在精确调用重复守卫（同参调用约第3次告警）。

## Discriminator
每次 pending 回执都单调给出 remaining_seconds，配合启动回执的 estimated_seconds/deadline 可算出 elapsed 并预判终态到达窗口；重复守卫一旦触发，其文本本身直接命名下一步动作（记 task_state 账本、勿继续重复探索）。

## Short path
- 启动受理后，按 waiting_protocol 发 status(child_id, wait_seconds=30)：一次调用同时完成查询与有界阻塞等待
- 每次返回先做算术：elapsed=deadline−remaining_seconds；elapsed 明显小于 estimated_seconds→继续一轮有界等待；接近或超过→下一查大概率终态
- 同一精确 status 已连发约2次仍 pending：先写 task_state 账本（child_id、已核 pending 序列、未决、下一步），使后续调用不再与被守卫调用完全同参
- 按回执协议换通道：普通 wait(≈30s) 返回后立即查 status；不连续只等墙钟，也不原样重发第4次
- 拿到终态后先做指纹绑定（candidate_sha256 前缀比对）再引用 PASS/P0/P1 结论

## Stop conditions
- qualification/child 出现终态且结论块 fingerprint 与启动回执 candidate_sha256 前缀一致
- remaining_seconds 耗尽或超 deadline：转入该闸的失败/重试合同，不再续等
- 任务书命名的停止条件或错误码触发：按其要求报告并停

## Verification
- 各次回视 remaining_seconds 单调递减、每次消耗≈wait_seconds，证明是有界等待而非空转刷调用
- 账本写入含已核事实与下一步，其后调用与被守卫调用不再完全同参
- 最终报告的 SHA/verdict 均有对应回执可溯源，无凭估计宣称终态

## Counterexamples
- 任务书/waiting_protocol 显式给出『原样重发至 N 次』预算且无重复守卫时，遵循其原样重发，勿插入多余账本写浪费轮次
- 回执不含 remaining/estimated 等量化字段：退回固定间隔有界轮询，不做算术排程
- 首次 status 即返回终态：无需轮询循环、账本或换通道
