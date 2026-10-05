---
method_id: measured-timeout-as-poll-lower-bound-4da80a3cf9e3
name: measured-timeout-as-poll-lower-bound
description: 长时本地工具（typechecker/全量测试/构建/索引器）同步运行已触发 executor timeout 后转后台时，把那次超时回执当作实测延迟下界 T 来调度监控：T 之前的任何状态轮询先验地无新信息；write-at-exit 重定向输出文件的大小不是进度信号。等 ≥T 再首次轮询（或用阻塞等待），用最少查询拿到终态结果。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:2780:eefbe9a58de3961a0899
evidence_refs: learning:learn:7ed29b47662a
created_at: 2026-10-02T10:46:04.651618+08:00
updated_at: 2026-10-02T10:46:04.651618+08:00
---
## Trigger
同步运行重型分析命令已收到超时回执，随后以后台任务+输出重定向方式重跑并需等待结果；或对任何后台任务反复 sleep+状态查询循环。

## Discriminator
轮询前已存在的两个事实：(a) 刚才的同步运行跑满 60s 未完成 ⇒ 该命令本机耗时 >60s，是实测下界 T；(b) 启动命令形如 `--outputjson > file`，文件在启动即被截断、工具结束时才一次性写入 ⇒ 0 字节/无变化不携带任何进度信息，只有任务终态有信息量。任何 <T 的轮询可证明不产生新事实。

## Short path
- 短命令直接同步跑；仅对已知重命令或已实测超时（得到 T）的任务转后台。
- 转后台时输出重定向到文件，并从回执原样复制 job_id（不手抄，本集手抄多了一个字符导致一次查询失败）。
- 启动后最多做一次立即查询，仅确认任务没有秒挂，不作为进度信号。
- 等待 ≥T（或使用 harness 的阻塞等待/完成通知原语）再做首次轮询，此后轮询间隔 ≥T。
- 读到终态+exit code 后一次性读取结果文件继续任务；若超过 ~2–3T 仍 running，停止 sleep 循环，转为挂起诊断（查进程/任务表）而不是继续睡。

## Stop conditions
- 任务状态为终态且结果文件可解析 → 停止轮询，进入下一步任务。
- harness 提供阻塞等待/完成通知 API → 直接使用，完全取消轮询。
- 超过 2–3T 仍非终态 → 切换为诊断动作，不再重复 sleep。

## Verification
- 只在终态后读取结果文件并确认可解析（如 summary.errorCount 等字段存在、exit code 已回显）。
- 复盘口径：除唯一一次启动确认外，返回相同信息（running/空文件）的轮询次数应为 0——本集为 3 次 sleep 轮询 + 4 次状态查询全部空转。

## Counterexamples
- 流式/增量输出工具（构建日志、逐行进度条）：部分输出是真实信号，早期轮询有信息量，不应套用。
- 预期远小于超时窗口的短命令：直接同步执行，后台+监控机制纯属开销。
- harness 已有阻塞等待/完成通知原语时：轮询整体被支配，方法不适用。
- 交互延迟敏感场景：启动后立即查一次确认没秒挂是合理的——但仅限这一次，不构成循环。
