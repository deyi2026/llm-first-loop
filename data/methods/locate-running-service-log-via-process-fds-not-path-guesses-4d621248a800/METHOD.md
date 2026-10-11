---
method_id: locate-running-service-log-via-process-fds-not-path-guesses-4d621248a800
name: locate-running-service-log-via-process-fds-not-path-guesses
description: 当需要用运行中进程/服务的日志验证事实（warmup、开关生效、错误现场）而不知道日志路径时：不要按惯例路径（logs/*.log、/var/log/...）猜测枚举；先取该进程 pid（回执或 ps 已给出），再列它打开的文件描述符，其中以写方式打开的 REG 文件就是它当前实际写入的日志，直接读该文件。适用于任何『已知进程、未知输出位置』的发现类子问题，把『猜路径→失败→再发现』压缩为一次 fd 查询直达权威路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:507:10c5542c3159a07a27e1
evidence_refs: learning:learn:57531071b08d
created_at: 2026-10-11T18:17:59.401698+08:00
updated_at: 2026-10-11T18:17:59.401698+08:00
---
## Trigger
需要查看某个正在运行的进程/服务产生的日志来确认事实（如 warmup 完成、特性开关生效、故障原因），日志文件路径未知，且该进程 pid 可从重启回执或 ps 获得。

## Discriminator
进入猜测动作前已可用的事实：(1) 目标进程 pid 已知（重启回执已给出 pid 与启动时刻）；(2) 同项目 runtime 产物已出现在非惯例目录（data/human_turn_queue.json），说明惯例 logs/ 路径不可靠；(3) 进程只要在写文件日志，其 fd 表中必有以写方式（1w/2w）打开的 REG 文件——这是当时即可用、且权威于任何路径猜测的定位手段。

## Short path
- 从重启回执或 ps aux 拿到目标进程 pid（解决：进程是谁、是否活着）
- 列出该 pid 打开的 REG 文件（lsof -p <pid> 或等价 fd 列表）（解决：日志实际写到哪里）
- 对唯一候选日志文件直接 tail/grep 目标标记行（解决：warmup/开关是否生效）
- 标记命中即停止发现，转入下一步任务动作（如入队/派发/汇报）

## Stop conditions
- fd 中定位到以写方式打开的日志文件，且读到目标标记行（其时间戳晚于进程启动时刻）
- fd 显示 stdout/stderr 接的是 pipe/tty（被 supervisor/journald 接管）→ 改用 supervisor 的日志通道，不再枚举文件系统

## Verification
- 所用日志路径必须出现在该进程自身 fd 列表中，而非来自惯例猜测
- 读到的标记行时间戳必须晚于该进程启动时刻（确认出自当前实例而非旧实例残留日志）

## Counterexamples
- 日志被 journald/docker/launchd 等接管：fd 指向 pipe/socket，没有 REG 日志文件，应改查 supervisor 日志命令而非 fd
- 需要历史/轮转日志：fd 只暴露当前活跃文件，旧轮转文件要靠配置或轮转目录
- 日志路径已在配置文件或文档中明确给出：直接读，跳过 fd 发现步骤
- 无权限查看目标进程 fd：退回读其启动配置或 supervisor 定义，不要反复换路径猜测
