---
method_id: failing-daemon-own-log-first-fix-at-real-supervisor-297cab3af0ce
name: failing-daemon-own-log-first-fix-at-real-supervisor
description: 复发型守护进程故障诊断：公网/本地各测一次定位故障层；用同机健康同类实例作对照排除环境；随后立即读故障进程自己的错误日志（经 lsof stderr 或 supervisor 元数据定位），而不是重复验证症状或做启动脚本/配置考古。若日志中拨打的地址与当前系统解析结果不一致，判定为进程内存缓存了坏地址，仅重启可清除；且修复必须写进真正托管进程的 supervisor 配置（launchd plist/systemd unit），否则 KeepAlive 会用旧配置把旧状态复活。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5693816b-bf5b-467a-8a25-a8f48a50e29b:237:9213c6427b6946100c1c
evidence_refs: learning:learn:6280a2855f91
created_at: 2026-09-22T16:34:47.762910+00:00
updated_at: 2026-09-22T16:34:47.762910+00:00
---
## Trigger
用户报告'上次修过但服务又坏了'，故障方是常驻后台进程（隧道/代理/web 守护），进程仍存活而对外服务异常（如公网 5xx、本地源站 200）

## Discriminator
同机同刻对照事实：故障实例进程存活但健康指标为 0（如 cloudflared ha_connections=0），同机另一同类实例指标全绿、本地源站 200。该事实当时即可把候选原因从'网络/DNS/配置/脚本'收窄为'该进程自身的边缘连接'，而答案就在该进程自己的错误日志里

## Short path
- 公网探测得症状码 + 本地源站 curl 200：故障隔离在 connector 层，不再重复验证已确立的症状
- ps 枚举同类进程：识别服务该域名的实例，以及是否存在同配置的重复 connector
- 逐实例查本机 metrics 健康计数：故障实例=0、健康对照>0 → 环境正常，问题在该进程内部连接
- 一步定位故障进程自己的错误输出（lsof -p PID 的 1w/2w，或 launchctl/systemctl 元数据里的 stderr 路径）并 tail：拿到直接失败原因，如持续 dial 某固定坏 IP 超时
- 用与进程一致的解析路径现场解析它正在拨的地址：结果正常而进程仍拨坏 IP → 进程内存地址池中毒，仅重启可清；结果仍坏 → 先修解析/代理层
- 确认真正的 supervisor 入口（plist/unit 及 KeepAlive），把修复参数写进该入口并由它重启，清掉重复实例后验证

## Stop conditions
- 故障进程日志给出的失败原因与当前独立观测（实时解析结果、健康计数）互相印证，即可执行 supervisor 级修复，不再扩大排查面
- 本地源站非 200：转修源站，本方法不适用
- 无健康对照且当前解析仍返回异常 IP：转向 DNS/代理层而非进程内部

## Verification
- 修复后该实例健康计数>0，且公网症状请求多次连续 200
- ps 确认运行参数与修改后的 supervisor 配置一致，且无同配置重复实例残留
- 所读日志时间戳与当前故障时段吻合，排除读到历史残留错误

## Counterexamples
- 源站本地即失败（local != 200）时读隧道进程日志无法定位，应先修源站
- 健康对照走不同协议/网络路径（如 QUIC/UDP vs TCP），其'全绿'不能证明故障进程的路径正常，对照只是弱证据
- 进程日志写入 journald/云端而非本地文件：lsof 找 stderr 无效，需改用对应日志接口
- 当前解析仍返回代理假 IP 时重启无效，须先恢复解析层，本方法不适用
- 无 supervisor 的手动前台进程：直接以正确参数重启即可，无需入口考古
