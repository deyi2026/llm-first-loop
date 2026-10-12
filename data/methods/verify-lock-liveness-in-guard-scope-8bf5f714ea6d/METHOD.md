---
method_id: verify-lock-liveness-in-guard-scope-8bf5f714ea6d
name: verify-lock-liveness-in-guard-scope
description: 当'能否重启/部署'取决于某些 run 是否仍活跃时，不要凭锁文件存在或他人汇报下结论：把候选范围限定在权威守卫机制实际检查的运行时目录，并用机械活性证据（lsof/flock 持有者、活 PID、事件日志仍在写入）一次判定活跃或陈旧，再决定等待还是 fail-closed 重启；吸纳外部代理的修复时同步独立核 diff、复跑测试、核对汇报的 HEAD/gen 基线。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:452:34567977524be31b8ff1
evidence_refs: learning:learn:0114d5b7e905
created_at: 2026-09-18T12:40:49.308710+00:00
updated_at: 2026-09-18T12:40:49.308710+00:00
---
## Trigger
任务前置条件是'确认某 run/进程是否仍活跃'（如重启门控、清理陈旧租约）；现场存在 *.run.lock 类租约文件，仅有他人汇报或文件存在性作为'活跃/僵死'依据，且重启失误会破坏正在运行的任务。

## Discriminator
宽枚举前已知：用户消息已点名具体锁 8264c548….run.lock，并说明门控机制基于'真实 *.run.lock'的运行时会话——因果域是运行时 sessions 目录；随后全仓 find 返回的候选绝大多数位于 evals/**/results（smoke-test 残留），仅凭路径即可预先排除，不在该因果域。

## Short path
- 未知量：8264 等运行时 run 是否仍活跃（决定能否重启）。直接对运行时 sessions 目录中用户点名的 8264….run.lock 做一次机械探测：lsof 锁 FD + ps 进程身份 + 事件日志 mtime 对比当前时间。
- 探测结果：锁被 PID 66137（llm_loop.runtime.launch web）持有、日志 20:30 仍在写 → 活跃，结论'必须等待'，不做任何强切。
- 若需'所有 run 空闲'全集：只列出运行时 sessions 目录的 *.run.lock 并用守卫同款 flock/lsof 逐个探测；evals 结果目录的锁按路径排除，不入门控。
- 并行独立吸纳：git show --stat → 分组核 diff 语义（守卫 fail-closed、模型 authority、newSessionPending 竞态、CPU 放大）→ 本地复跑 focused tests → 核对 deployment gen/HEAD 与汇报逐项一致。
- 全部通过且锁活跃 → 挂'等空闲（同款探测）→复核 HEAD→重建 WebUI→publish→fail-closed 重启→canary'后台链，停止进一步探索。

## Stop conditions
- 权威探测显示锁无活持有者（lsof 无 FD / 进程已退 / 日志 mtime 停滞）→ 判定空闲，进入重启流程。
- 探测显示锁被活进程持有且日志仍在写 → 不重启、不强切，挂等空闲后台链后停止。
- 独立复跑测试失败，或实际 HEAD/工作区/deployment 与汇报不符 → 中止吸纳，留人工裁决。

## Verification
- lsof/flock 显示锁 FD 被具体活 PID 持有（本例 PID 66137）且命令行与运行时进程一致；事件日志 mtime 与当前时间差在秒级（活跃）或明显停滞（空闲）。
- 本地独立复跑声称的测试全数 PASS（本例 95/95），并核对 deployment generation/HEAD 与汇报一致（gen28=8704f0b29、候选 commit 在祖先链、tracked 零脏）。

## Counterexamples
- 锁是无 FD 绑定的普通标记文件（创建后即关闭）时，'lsof 无持有者=空闲'不成立，必须换心跳/mtime/写序号等活性信号——不套用本方法的机械探测分支。
- 存在权威 status API/deployment 元数据直接返回 active runs 时，优先消费该权威来源，不自建 lsof 探测。
- 任务目标本身就是清理或审计全部历史锁文件（含 eval 产物）时，全仓枚举恰是目标，'限定运行时目录'不适用。
