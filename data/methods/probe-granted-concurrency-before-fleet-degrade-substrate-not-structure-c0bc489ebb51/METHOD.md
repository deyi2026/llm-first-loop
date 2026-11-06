---
method_id: probe-granted-concurrency-before-fleet-degrade-substrate-not-structure-c0bc489ebb51
name: probe-granted-concurrency-before-fleet-degrade-substrate-not-structure
description: 用户要求并行协同提效时，第一未知量不是『怎么拆 lane』而是『运行时实际授予多少并发』。协调回执的 capacity 槽位不等于并发授予。先用一个带紧预算的最小 canary 子任务实测：若回执出现租约超时/上下文耗尽/子任务被串行化等运行级信号，即判并行基底不可用，立即把执行基底降级为主会话按 lane 串行，但保留按文件冲突面拆的 lane、逐 lane 独立红→绿 commit 与合并审查闸。运行级失败不重发同构 fleet、不推翻任务结构，只换执行基底。
aliases: 并行提效先测子代理能不能真并发, 子代理一直租约超时怎么办, 开了多个子代理其实只能串行跑, 并发能力先探测再拆并行任务, 多代理协同跑不动就串行保结构
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3319adeb-e84e-4f85-ae10-8306e3d98fb1:138:ae8b8a4bdb1a38574c2c
evidence_refs: learning:learn:8a90a9b45a9b
created_at: 2026-11-06T14:31:06.690539+08:00
updated_at: 2026-11-06T14:31:06.690539+08:00
---
## Trigger
任务书要求安排协同并行子任务提高效率，运行时提供子代理委派接口，但本会话尚无任何子代理成功并发运行的直接证据；协调回执只披露容量槽位与在跑数，不能据此认定并发可用

## Discriminator
进入 fleet 前已可见三件事：协调回执 children=0/jobs=0，只有 capacity 槽位、无并发授予证据；环境方法记忆开局检索已命中『子代理运行级死亡（上下文爆窗/租约超时/轮次上限）』的历史卡，证明本环境委派基底有已知脆弱性；事件流同窗口还出现 provider prefix_broken 级运行不稳记录。三点合力足以把『直接铺开多 lane fleet』收缩为『先花一个最小 canary 实测并发』

## Short path
- 按修复清单×文件冲突面拆 lane：互不交文件的 lane 可并行，共改同一文件的条目并入同 lane 串行——此步不依赖运行时并发能力
- 派发一个带紧预算的最小 canary 子任务，未知量=运行时实际授予的并发
- 读 canary 回执分流：正常并发完成→按原 fleet 派发；租约超时/上下文耗尽/被串行化→判运行级并行不可用
- 降级执行基底而非任务结构：主会话按 lane 串行执行，保留逐缺陷独立 commit、红→绿基线、合并审查闸与可单独 revert 的边界
- 合并/验收/部署照常走门禁；遇外部通道故障做有界诊断后交恢复路径，不在同一通道无限重试

## Stop conditions
- canary 正常并发完成，fleet 已按 lane 成功派发并各自有产出
- 全部 lane 在串行基底上红→绿且合并门禁通过、非退化基线确认
- 运行级失败定性完成后，不再向同一委派基底重发同构 fleet

## Verification
- 降级仅当失败类别是运行级（租约/上下文/串行化），而非任务级（测试红、补丁缺陷）——后者走正常修复迭代
- 降级后产物完整性不缩水：每缺陷独立 commit、基线测试非退化、合并预演零冲突
- 最终门禁回执（测试/lint/部署 generation）与逐 lane 提交树可一一对账

## Counterexamples
- 协调回执或事件流已有多个子代理并发跑完的先例→无需 canary，直接派发 fleet
- 任务硬性要求子代理隔离（盲评、防串扰）→不能换主会话串行，只能接受更慢或换环境
- 子代理失败是测试失败/补丁缺陷等任务级问题→不适用基底降级，走常规修复循环
- 工作本身单 lane、无文件冲突面可拆→根本不存在并行结构设计问题
