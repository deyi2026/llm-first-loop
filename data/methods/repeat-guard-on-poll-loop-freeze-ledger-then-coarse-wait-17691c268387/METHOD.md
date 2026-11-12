---
method_id: repeat-guard-on-poll-loop-freeze-ledger-then-coarse-wait-17691c268387
name: repeat-guard-on-poll-loop-freeze-ledger-then-coarse-wait
description: 被任务书指示的固定参数轮询循环（如 status(child_id, wait_seconds=30) 查异步审查终态）在仍非终态时触发环境反重复护栏 repeat_guard：护栏按精确调用计数、与墙钟间隔无关，且回执点名纠正动作（先把已核事实记入 task_state 账本、停止重复探索）。此时不放弃循环目标、也不原样重发：一次固化固定上下文（child_id、冻结指纹、scope、pending 状态与剩余预算、下一步），把节奏腿换成普通 wait 的有界分块（远小于 deadline），每段 wait 后立即一次 status 权威核验；预算 estimate 不是 ETA，终态可能提前到达，故分段而非睡到预估点。终态逐字段核对 qualification/artifact_reviewed/指纹一致后闭账输出。
aliases: 轮询触发repeat_guard后怎么等, 重复查询护栏改等待节奏, pending审查别刷status改wait, 先记账本再粗粒度等待, 长时审查轮询降频, 同参数轮询被拦换wait分块
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4719d425-c1da-4544-874e-bf639948d263:0:ca19e898abbd347eae6c
evidence_refs: learning:learn:de728d09b249
created_at: 2026-11-12T15:11:58.828838+08:00
updated_at: 2026-11-12T15:11:58.828838+08:00
---
## Trigger
异步子任务或准入审查的终态需靠固定同参轮询获得，且轮询回执触发 repeat_guard（『该精确调用本 run 已第 N 次成功执行…先记 task_state 账本，不要继续重复探索』），或启动回执的预算元数据（remaining/deadline）与轮询间隔之比达数十倍，表明细粒度轮询近零信息

## Discriminator
当时已知两条可观察事实：(1) repeat_guard 回执本身命名的纠正动作——记入账本、停止重复；其判据是精确调用重复而非调用频率，原样重发必然再次触发；(2) 启动回执 review_budget 的 remaining/deadline 与 30s 轮询间隔之比约数十倍，而工具 schema 同时允许『普通 wait 返回后立即查 status』的节奏。二者合起来把『每 30 秒枚举一次终态』缩成『一次上下文固化＋少数几次有界等待后的权威核验』

## Short path
- 循环目标不变（轮询到真实终态）；首个 pending 回执后即把固定上下文一次写入 task_state 账本：child_id、冻结指纹（candidate_sha256 等）、scope/paths_ignored、当前 pending 与预算、下一步动作
- 节奏腿从同参 status 换成普通 wait 有界分块（如 120s，远小于 deadline）；预算只用来证伪『必须细粒度轮询』，不当 ETA 用——终态可能远早于 estimate 到达，故保持分段
- 每段 wait 返回后立即查一次 status 作为权威核验，不连续只等墙钟
- 终态回执逐字段核对：qualification 非 pending、artifact_reviewed=true、指纹与启动时冻结一致、child_state=completed；reviewer 自述 PASS 不单独算数
- 再取 reviewer 详细发现（P0/P1/P2）填任务书要求的报告字段，闭账本，按指定格式输出

## Stop conditions
- status 返回真实终态（如 qualification=PASS/REVISE）且 child_id/指纹与账本冻结值一致
- 护栏之外出现运行级失败或超限信号，节奏优化不再适用

## Verification
- 启动与终态两份回执的 candidate_sha256/child_id 完全一致
- 每段 wait 之后都有一次 status 核验，无连续纯墙钟等待
- 账本闭账记录含终态字段，且未执行任务书禁止的动作

## Counterexamples
- 任务书以『等待参数＋次数上限』定义轮询预算、环境无反重复护栏且非终态回执提示可稍后再查时，应按原样有界重发并计数（bounded-blocking-polls 卡），不改造节奏
- 多个审查并行时 status 轮询一次可顺带查多个 child，换成单 child 墙钟等待反而增加总调用数
- 剩余预算已不足一两个轮询间隔或逼近 deadline 时，粗等待可能错过终态或超限，应保持细粒度
- 轮询每次返回增量信息（分页进度、日志增长）时本不应触发护栏；若触发说明调用参数未变，应先修调用而非等待节奏
