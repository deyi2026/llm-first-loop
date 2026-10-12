---
method_id: detach-never-exiting-helpers-then-inline-probe-f5b9e5bd9255
name: detach-never-exiting-helpers-then-inline-probe
description: 启动长期辅助进程（本地 fixture HTTP 服务、daemon、watcher、tail -f）前，先按命令语义判断它是否会自行退出。对永不退出的进程，禁止在『等待命令退出/带超时』的命令工具里前台运行：必然以工具超时收场，且子进程生命周期被绑定到该次调用、随之被杀，被迫进入『超时→连接拒绝诊断→重启』循环。正确做法是一条组合命令完成：分离启动（nohup … & disown 或平台后台任务通道）+ 短暂 settle 等待 + 带超时的内联探针（curl -m）打到确切目标资源并校验状态码与字节数；调用返回后再用独立探针确认存活；重启前必读日志。可把 3 次调用（含一次 60s 必然超时）压缩为 1 次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1284:1bfe3923337be77621e4
evidence_refs: learning:learn:170c6937a6f2
created_at: 2026-09-18T05:46:28.256388+00:00
updated_at: 2026-09-18T05:46:28.256388+00:00
---
## Trigger
需要经由『等待命令退出/带超时』的命令工具启动一个长期存活的辅助进程（本地 fixture HTTP 服务、daemon、文件 watcher 等），且后续测试步骤依赖它在多次工具调用之间持续存活。

## Discriminator
待执行命令本身的语义在发起调用前就显示它永不自行退出（如 python -m http.server 会一直 serve 直到被杀）；而命令工具要等命令结束才返回。两者组合即可预判：前台启动只能以工具超时结束，且子进程会随调用被杀——无需先失败一次才知道。

## Short path
- 按命令语义分类：会自行退出的一次性命令 vs 永不退出的服务型命令（server/daemon/tail -f/listen）。
- 若属永不退出：合成一条命令 = 分离启动（nohup … >log 2>&1 & disown，或平台持久后台任务通道）+ 短暂 settle 等待 + 有界探针（curl -m N）请求确切 fixture URL 并校验状态码与字节数。
- 读探针结果：状态/字节符合预期 → 辅助进程已验证，直接进入正式测试；启动失败（端口占用/文件缺失）→ 先读服务日志修配置，再仅重试一次，不盲目重发。
- 记录 pid/job_id 与日志路径，供最终清理。

## Stop conditions
- 探针返回预期 HTTP 状态码且下载字节与 fixture 实际大小一致（如 200 + 全量字节数）。
- 服务日志显示确定性启动失败（端口被占用、文件不存在）→ 停止重试，先修配置再重启。

## Verification
- 启动调用结束之后，用一次独立的有界探针（新调用，curl -m 5）再次命中同一 URL 仍成功，证明辅助进程活过了它的启动调用而非随调用被杀。
- 清理阶段能凭记录的 pid/job_id 干净终止，无孤儿进程残留。

## Counterexamples
- 一次性命令（ls、curl、pytest）自身会退出：应保持前台执行，分离反而制造孤儿进程。
- 刻意让辅助进程只活在单次调用生命周期内的场景（起→打→随调用自动回收）：前台正是设计意图，不应分离。
- 平台会在调用之间回收 detached/孤儿进程的环境：裸 nohup 无法存活，必须改走平台持久后台任务通道（job_id）。
- 服务预热时间超过内联等待窗口：内联探针需为有界重试循环，否则假阴性会被误诊为『启动失败』而触发错误修复。
