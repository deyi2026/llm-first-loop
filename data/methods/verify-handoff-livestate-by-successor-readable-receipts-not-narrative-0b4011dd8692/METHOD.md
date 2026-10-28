---
method_id: verify-handoff-livestate-by-successor-readable-receipts-not-narrative-0b4011dd8692
name: verify-handoff-livestate-by-successor-readable-receipts-not-narrative
description: 接手跨会话交接文档时，文档里『某子代理正在运行、将产出 X』的 live-state 断言只对发起会话可核验：子代理句柄是 parent-session 私有的，后继会话直接轮询会收到『仅直接 parent 可以读取该 child handle』的授权失败。应把每条在飞断言当待核假设，逐项用后继会话可读的机械状态（进程表、文件系统产物、调度 store、topology/结算回执）核对后再规划等待或重做；授权失败 + topology 显示 cancelled + 承诺产物缺失 = 结构性信号：该工作不可继承，须在本会话按原协议重派，而非继续设法领养旧句柄。对确实存活的进程（pid + 日志推进）则保留祖父条款，不整体推倒。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40fc9238-e2b7-4c72-a023-f7e53ee023da:1:ef3b347733cf340b58dd
evidence_refs: learning:learn:4c7f8da4b1c3
created_at: 2026-10-19T20:20:11.309720+08:00
updated_at: 2026-10-19T20:20:11.309720+08:00
---
## Trigger
新会话接手一份交接文档，文档断言存在后台/在飞工作（子代理运行中、跑批进程、定时兜底、承诺将产出某文件），且下一步规划（等待/轮询/汇总）依赖这些『在飞』状态为真

## Discriminator
对继承来的 child handle 发起轮询直接返回授权失败『仅直接 parent 可以读取该 child handle』——句柄是 parent 会话私有的；随后可取的 topology 回执给出 outcome=cancelled、settlement_state=collected、last_parent_session_id=前一会话≠当前；同时 ls 显示文档声称『运行中子代理将产出』的文件不存在。三者任一在规划前出现，即证明交接叙述的 live-state 已过期且不可继承，无需再试任何领养方式

## Short path
- 读交接文档，机械列出全部『在飞』断言项：进程 pid、子代理 handle、计划任务、承诺产物路径
- 逐项一次核验，只用后继会话可读状态：ps 验 pid 是否存活；ls 验承诺产物是否落盘；子代理不重试轮询，直接取 topology/结算回执读 outcome 与 last_parent_session_id
- 按核验结果分流：pid 存活且日志推进 → 保留等待并把结果可用性挂门（祖父条款）；handle 为 cancelled 且产物缺失 → 判定不可继承，在本会话按原协议重派（写码/只读审查分离，审查 PASS 前不花全量 API）
- 重派只重建执行，沿用交接中已冻结的决策与红线（门槛冻结、口径并列、不写 PASS），不借机改口径
- 把每项核验结论写回交接事实表，供下一棒直接使用，避免再次基于过期 live-state 规划

## Stop conditions
- 所有在飞断言项均已获得后继会话可读的三态结论（alive / cancelled / absent），没有仅凭叙述的待办
- 不可继承项已在本会话按原协议重派，产物落盘并通过独立验收
- 可继承的存活进程已建立结果可用性挂门，不再追加轮询或领养尝试

## Verification
- topology 回执中 last_parent_session_id ≠ 当前会话且 outcome 非 running，证实是级联取消而非瞬时查询失败
- 重做产物做一致性验收：语法编译通过、输出与既有权威实现一致、同输入两次运行逐字节一致
- 存活进程用 ps + 日志尾部推进记录双重确认，而非只信交接文档或单次 ps

## Counterexamples
- 交接只声称持久工件（已写盘文件、冻结 JSON、共享 store 里的调度条目）：直接核验工件存在即可，不触发『重做』分支
- 平台显式支持跨会话领养子代理（持有 grant 的任意会话可读 handle）：一次成功轮询即更新状态，授权失败不会出现，本判据失效
- 进程存活且日志持续推进：该项按祖父条款保留等待，不能因『不信任交接叙述』而整体推倒重跑（该分支由 grandfather-inflight-run 卡覆盖）
- 无任何机械核验途径（无进程表/文件系统/回执可读）：只能按假设双分支规划并显式标注未核验，本方法的具体判据不可用
