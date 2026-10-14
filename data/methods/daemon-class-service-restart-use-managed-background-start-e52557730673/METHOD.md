---
method_id: daemon-class-service-restart-use-managed-background-start-e52557730673
name: daemon-class-service-restart-use-managed-background-start
description: 重启/启动常驻服务前，先用可观察谱系（uptime、supervisor 命令行、日志重定向）判定目标是否守护型前台服务。守护型目标必须经受管后台任务或等价脱离方式启动，禁止放进有界超时的阻塞 shell：超时清理会连同进程组杀掉刚启动的服务（本集 run3 日志证明服务已启动出 URL 却被 60s 超时清理杀死，被迫二次重启）。同时不要在启动机制验证可行之前先 TERM 旧实例，避免拉长停机窗口。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:dbb11178-e3d2-4816-96e3-05377a07ca5b:52:034d0b285a011a51ef41
evidence_refs: learning:learn:d6a2ced115f5
created_at: 2026-10-13T18:50:54.048788+08:00
updated_at: 2026-10-13T18:50:54.048788+08:00
---
## Trigger
需要对一个常驻服务（如 dsh web）执行重启使改动生效，且尚未决定新实例的启动机制时。

## Discriminator
启动动作之前已可见：目标进程 uptime 以天计（Sun 7PM 起跑，远大于工具 60s 超时）；其 supervisor 行为 `/bin/sh -c cd … && dsh web > /tmp/…log 2>&1`（脱离+重定向，无可等待前台）。这说明它是前台永不返回的守护型服务，放进有界超时的阻塞执行器必然在超时时被连同进程组一起清理。

## Short path
- ps 查目标 PID 与启动谱系（解决未知量：哪个进程、如何被监管）。
- 核对通道归属（本例：DSH vs LFL feishu）确认重启不打断用户会话（解决未知量：是否安全）。
- TERM 旧 PID 并确认退出+目标端口释放。
- 依据守护型判别直接经受管后台任务启动（--no-open、日志重定向），沿用旧 supervisor 行的脱离模式，跳过任何阻塞式启动尝试。
- 验证：新 PID 命令行含预期参数、端口 LISTEN、HTTP 探活返回鉴权类响应、日志出现服务 URL。
- 核验重启目的已达成（如 plugin list 含目标且无 Problem 标记）后停止。

## Stop conditions
- 新实例经 PID+端口+探活+日志多重验证存活，服务恢复。
- 重启目的已由权威回执验证（插件已加载/配置已生效），停止后续动作。
- 若旧实例已停却发现无可信启动机制，先恢复服务或回滚，不在停机状态下试错。

## Verification
- ps 确认新 PID 存在且命令行含预期参数（如 --no-open）。
- lsof 确认目标端口 LISTEN 归属新 PID 而非残留旧进程。
- HTTP 探活非 connection refused（401 等鉴权响应即证明服务存活）。
- 后台任务重定向日志中出现服务就绪行（URL/token）。

## Counterexamples
- 短生命周期命令（build/test/数据迁移）：应留在阻塞执行器里拿退出码与输出，后台化反而丢失失败证据。
- 目标由显式生命周期控制面管理（如 service_control 的 web/feishu/learning restart，由 detached worker 执行）：走控制面，不要手动 kill+start。
- 需要同步读取 stdout/退出码的快速一次性命令：守护型判别不适用（uptime 短、无可观察脱离谱系）。
