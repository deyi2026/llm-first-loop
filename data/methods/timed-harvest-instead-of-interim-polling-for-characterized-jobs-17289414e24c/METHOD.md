---
method_id: timed-harvest-instead-of-interim-polling-for-characterized-jobs-17289414e24c
name: timed-harvest-instead-of-interim-polling-for-characterized-jobs
description: 后台长任务（复测/评测/批处理）若已有同款首跑刻画出时长与输出缓冲行为，起跑拿到 job_id 与 running 回执后，不要在已知时长窗口内反复做无信息轮询（sleep+tail 空日志、重复查 job 状态、ps 确认存活）；应立即注册定时唤醒，把收割动作（读完成日志、判 gate、核对旧失败签名是否消失、冻结回执、回填诊断文档、汇报）写成清单挂到唤醒点，等待窗口用于并行做独立确定性工作。若唤醒时仍在跑，按清单再排一次，不重启任务。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:522:6ef8a76156834129d763
evidence_refs: learning:learn:fdf80e118970
created_at: 2026-09-17T23:52:21.145730+00:00
updated_at: 2026-09-17T23:52:21.145730+00:00
---
## Trigger
刚启动一个后台长任务，且同一 runner/命令此前已完整跑过一次（时长与日志缓冲行为已知），任务系统回执已给出 job_id 与 durable 的 running 状态。

## Discriminator
三条当时已存在的事实叠加：①预计完成时间远在当前之后（约20分钟 vs 只等了45秒）；②日志为行末缓冲，中途 tail 必为空（首跑同款行为）；③job 系统已回报 state=running——此时任何中期状态查询都不改变下一步动作，唯一正确动作是把等待换成定时收割。

## Short path
- 启动复测 run，从回执记下 job_id、日志路径、state=running（未知量：修复是否改变测量结果，只能由完成后的日志回答）
- 立即注册定时唤醒（≥预计时长+余量），提醒中写全收割清单：读日志与 summary、判 gate、逐行核对旧失败签名是否消失、冻结回执、回填诊断文档、checkpoint、向用户汇报，并注明'仍在跑则再等再查，不重启'
- 用等待窗口完成独立工作：写/提交诊断文档中不依赖 run 结果的部分
- 向用户汇报当前状态后结束本轮，等待唤醒
- 唤醒时按清单收割；若仍未完成，按同一清单重排唤醒

## Stop conditions
- 唤醒已注册且回执状态为 running：不再做任何中期状态查询
- 收割清单全部执行并已向用户汇报：本轮收口
- 出现早期崩溃信号（回执失败、任务秒退、日志已报错终止）：才转入即时排查分支

## Verification
- 起跑到唤醒之间的无信息状态查询（tail 空日志、重复 job_output、ps 存活确认）计数应≤1
- 唤醒点存在且携带完整收割清单，而不是裸 sleep 或空提醒
- 最终结果仍来自同一 runner、同一预检的完成日志，任务未被中途重启

## Counterexamples
- 首次运行或时长未知的任务：一次约60秒的早期存活检查能捕获启动即崩（导入错误、端口冲突），高信息量，不应省略
- 历史不稳定或易 OOM/卡死的任务：中期巡检有真实止损价值，不应被定时唤醒取代
- 预计两分钟内完成的前台短任务：同步等待比注册唤醒更简单
- 任务系统不回报状态且无其他进程可见性：一次 liveness 确认是必要的，本方法前提（状态已被回执证明）不成立
