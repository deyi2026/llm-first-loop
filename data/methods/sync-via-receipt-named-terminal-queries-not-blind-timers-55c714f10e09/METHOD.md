---
method_id: sync-via-receipt-named-terminal-queries-not-blind-timers-55c714f10e09
name: sync-via-receipt-named-terminal-queries-not-blind-timers
description: 后台/异步操作（后台 pytest job、服务 restart、评审子代理）的受理回执都会点名终态查询入口与终态谓词，部分入口自带等待参数（如 subagent_result(wait_seconds)）。把这些点名入口当作唯一同步原语：优先用自带等待的查询一次完成等+查；纯定时 wait 必须与状态查询交替，绝不连续盲等；步长按同负载上次实测时长（约 T/3）或进度输出修正；命中终态立即读回执点名的工件并停止；终态依赖本会话外条件（如 barrier 等 requester 退出）时声明待办、不再轮询。本集多个后台任务各耗 5~9 分钟，盲等/检查交替贡献了大量重复调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:2677:74da7e12a7b9f92a3def
evidence_refs: learning:learn:3472f6e77799
created_at: 2026-10-13T20:48:45.440182+08:00
updated_at: 2026-10-13T20:48:45.440182+08:00
---
## Trigger
启动后台 job / 异步服务操作 / 子代理后需要同步其完成，且受理回执点名了查询入口（job_output、service_control(action=status)、event_stream(query=service_action_terminal)、subagent_result(wait_seconds=…)）与终态谓词（status=done/succeeded/failed）

## Discriminator
回执文本是否点名可查询/可等待的终态入口，以及是否存在同负载上次运行的实测时长或进度输出可用来设定步长；若查询调用自带 wait/timeout 参数，则独立的盲等定时器调用即为冗余

## Short path
- 读受理回执，提取点名查询入口、终态谓词、产物路径（action_id/child_id/日志文件）；若仍有在收集旧代码的 in-flight 复现任务，先终止再起新验证任务
- 优先用自带等待参数的查询调用（如 subagent_result(wait_seconds=30)）把等待与检查合并为一次调用；无此参数则 wait(步长≈上次实测T/3) 后紧跟一次状态查询
- 每轮按返回的进度/剩余量修正下一等待步长；两次纯定时 wait 之间必须插入一次查询
- 命中终态谓词立即读取回执点名的工件（cat 日志 / action 摘要），以工件实值验证结论并停止同步
- 若回执表明终态依赖本会话外条件（restart barrier 等 requester 会话退出），声明为机制性待办并转入其他可推进工作（如并行评审子代理），停止对该条件轮询

## Stop conditions
- 终态查询回执显示 done/succeeded/failed，且已读取并核验点名工件的实值
- 终态依赖本会话外/不可观测条件，记为待办后停止轮询
- 查询返回参数契约错误：按回执一次性修正全部字段后重试一次，不逐字段试探

## Verification
- 轨迹中不存在连续两次纯定时 wait 而中间无状态/输出查询
- 最终状态断言引用终态查询回执与工件实值（如日志行 '7575 passed'），而非计时推断
- 同类后台任务的同步调用数较盲等轮询下降，且无终态达成后的空转等待

## Counterexamples
- wait 工具本身支持按目标/条件等待（非纯定时器）→ 直接用它即可，无需轮询纪律
- 秒级前台任务（如 18s 的隔离测试）→ 同步执行即可，套此法反而增加调用
- 把方法误读为高频短轮询：对已知约 6 分钟的回归套件每 5s 查一次会推高重复调用；步长必须来自实测时长或进度证据
- 终态由外部条件决定（会话退出触发 restart barrier）时轮询无意义，声明待办即可
