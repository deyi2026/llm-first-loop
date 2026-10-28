---
method_id: verify-setpoint-then-event-gate-for-async-structural-assertion-24dfbfbf31a5
name: verify-setpoint-then-event-gate-for-async-structural-assertion
description: 时序测试用『耗时<Xms』仅作为异步/非阻塞意图的代理、在 CI 负载下抖红并决定改写为结构断言时：先读测试体分离『意图断言』与『计时代理』（计时断言后紧跟 wait-background helper 即证明意图是异步性）；再锚定生产代码定义，确认可观测标志相对被测调用返回点是锁内同步置位还是 worker 内异步置位——这一条决定直接断言是否无竞态；最后在 fake 依赖的后台线程唯一阻塞点装 test-owned threading.Event 闸门，用『已进入未返回＋同步标志』三件套替换时间阈值。比放宽阈值严格更强：最快真回归形态（同步完成约20ms）原阈值漏检、新断言必红。
aliases: 毫秒断言改结构性断言怎么改, flaky 时间阈值断言加固, 用 threading.Event 证明没等后台, 非阻塞测试不靠计时, CI 时序抖红改写断言, 后台任务已提交的确定性断言
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:1090:274682b8c4a0bb0faaa1
evidence_refs: learning:learn:1216d0a19ade
created_at: 2026-10-27T23:03:05.575156+08:00
updated_at: 2026-10-27T23:03:05.575156+08:00
---
## Trigger
测试用『耗时 < Xms』断言充当异步/非阻塞/已提交等结构性质的代理指标，在 CI 负载下抖红（或预防性加固），且已决定改写为结构断言而非放宽阈值或加 retry

## Discriminator
测试体自身结构已暴露意图：计时断言后紧跟等待后台完成的 helper，说明测试本来就预期工作在调用返回后才完成，阈值只是『没阻塞』的代理；同时锚定读取生产调度函数定义后可见：可观测标志在被测调用返回前、锁内同步置位（决定直接断言无竞态），且 fake 依赖中后台线程存在唯一可替换的阻塞点（sleep）

## Short path
- 读测试体：把『意图断言』（首查热命中、跨会话隔离等）与『计时代理』（save_ms<30）分开，列出必须原样保留的断言
- 判别测试自身结构：计时断言后是否紧跟 wait-for-background helper——是则意图为异步性，走结构改写；若阈值本身就是契约则停止（见反例）
- 锚定 grep 生产代码中调度函数的定义（带 def 前缀，避免命中调用点），回答唯一未知量：可观测状态标志在调用返回点之前同步置位，还是 worker 线程内异步置位
- 读 fake 依赖，找后台线程唯一阻塞点，设计 test-owned threading.Event 闸门（entered/release）替换原 sleep delay
- 落新断言三件套：调用返回后 entered 已置（后台已启动）∧ returned 仍为 False（主路径没等它）∧（若确认同步置位）inflight 类标志为 True；意图断言全部保留
- 本地连跑 3 次全绿 + lint/type 门禁，推送后以 CI 逐项回执核对，并做反向红测验证

## Stop conditions
- 结构断言三件套落地、原意图断言保留、本地重复运行稳定、远端 CI 对应 job 转绿
- 反向验证通过：人为让该后台工作同步执行时，新断言必红
- 断言所用标志的置位语句已在源码定义处确认位于被测调用返回之前（锁内），无竞态窗口

## Verification
- 临时把后台调度改成同步执行（或让 fake 立即返回）跑一次：gate 断言应变红；同时确认原 <30ms 阈值在该回归形态（约 20ms 完成）下仍绿——证明改写是强化而非弱化
- 审核时用『最快真回归形态原来是否被阈值漏检』裁决是否弱化断言，而非凭直觉
- CI 通过后核对远端权威 commit 与本地一致，不依赖陈旧的本地 remote-tracking ref

## Counterexamples
- 阈值本身就是要测的契约（延迟 SLA/预算测试，如 p99<200ms 是需求）——不能换成结构断言，应保留计时并用宽松裕度或统计化处理
- 被测路径在特定模式下合法地同步等待后台（条件性 sync flush）——『未返回』断言会误报，必须按模式分支
- fake 依赖闸不住后台线程（真实网络、不可注入的外部线程池）——Event 闸门不可用，需埋点或进程级观测
- 可观测标志只在 worker 线程内异步置位——调用返回后直接断言该标志存在竞态，只能依赖闸门断言或先给生产代码补同步置位点
