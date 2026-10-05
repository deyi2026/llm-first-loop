---
method_id: dead-port-owner-via-tunnel-pairing-and-proxy-ppid-e5ccf36660b5
name: dead-port-owner-via-tunnel-pairing-and-proxy-ppid
description: 本地端口挂掉后的归属诊断：不按名字枚举 launchd/配置/仓库，而是沿已存在的基础设施 provenance 边直接跳到所有者。(1) watcher 日志中 local/pub 的逐行状态配对（000↔502、411↔411）是端口↔公网域名的机械映射证明；(2) 隧道/代理进程（如 cloudflared）的 PPID 即同时拥有隧道与内嵌后端的应用，一跳定位；(3) 桌面应用重启前先处理孤儿 helper（否则 LaunchServices 判定已运行使 open -a 静默 no-op）与含死 pid 的陈旧锁文件；(4) 用 watcher 的健康签名（如 POST 无 body→411）做恢复验证。仅在无此类边或边被证伪时才退回宽枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0bef697d-47ee-4725-9de3-16add287df21:21:1f9a532c988bf1667d95
evidence_refs: learning:learn:810cf5236304
created_at: 2026-10-04T21:47:21.976552+08:00
updated_at: 2026-10-04T21:47:21.976552+08:00
---
## Trigger
本地端口服务不可达（connection refused / 无监听），需要回答『哪个进程/应用拥有该端口、为何没起来』，且环境中已出现显式引用该端口的基础设施 artifact：隧道/代理进程（cloudflared 等）与监控 watcher 日志（内含 local/pub 逐行探测配对）。

## Discriminator
watcher 日志把 127.0.0.1:8790 与公网域名逐行配对，且 local=000 的行 pub 恰为 502、local=411 时 pub=411/401——这种逐行相关是『公网域名经隧道映射到本端口』的机械证明；同时 ps 已显示活跃的 cloudflared tunnel（--token 模式）。两者结合把候选所有者从『所有名字含 mcp 的服务/配置/仓库』缩成『启动并拥有该隧道进程的应用』：查其 PPID/launchd label 一跳即得，无需按名字枚举。

## Short path
- 探活确认：curl/lsof 确认端口无监听（未知量：服务是否存活）；失败形态是 connection refused 而非超时，说明本机无监听者而非网络问题。
- 读取引用该端口的 watcher 日志（未知量：该端口绑定哪个外部端点、健康签名是什么）：提取 local/pub 逐行配对关系与存活签名（如 POST 无 body→411）。
- 沿隧道 provenance 一跳找所有者（未知量：谁同时管理隧道与内嵌后端）：ps -o ppid,lstart,command -p <隧道PID> / launchctl print，定位父应用。
- 在该应用的支持目录验证归属与死因（未知量：能否安全重启）：instance/profile 锁文件中的 pid、sidecar 日志截断点、既有 crash 报告文档。
- 解除重启阻断后拉起（未知量：为何直接重启无效）：pkill 孤儿 helper/残留进程→删除含死 pid 的陈旧锁→重新启动应用。
- 用 watcher 健康签名验证恢复（local=411 且 pub=411、隧道新 PID），验证通过即停。

## Stop conditions
- local 恢复健康签名且公网映射端点同步恢复（隧道重建），『归属+死因+恢复』三个未知量均已闭环。
- provenance 边被证伪：pub 失败与 local 状态不相关，或隧道父进程无法指向明确应用——此时才退回 launchd/配置/仓库的按名枚举。
- 已获得权威归属证据（锁内死 pid、父进程关系、sidecar 日志、既有崩溃报告）即停止枚举其他候选服务。

## Verification
- 归属结论必须有机械证据（锁文件 pid、PPID、sidecar 日志、既有 crash 报告）支撑；端口号相邻（如 8791/8799 有进程监听）或名字相似均不构成证据，不应据此改写问题为『服务挪了端口』。
- 恢复后用与健康基线一致的探针同时验证 local 与 pub 两端，并确认 watcher 日志恢复健康行。
- 死因表述与证据形态一一对应（日志戛然而止且无 .ips 崩溃报告=静默死亡；与既有崩溃家族文档比对触发条件而非症状）。

## Counterexamples
- 端口仍在监听：lsof -iTCP:<port> -sTCP:LISTEN 直接给出 PID，不需要本方法。
- 全新 ad-hoc 开发服务、无任何隧道/watcher 引用该端口：provenance 边不存在，应先查监听表与 launchd，而不是找代理进程的父进程。
- pub 端点 502 由其自身后端故障造成、与 local 状态不相关（逐行不配对）：配对是巧合，不能据此断言映射关系，需改查 tunnel ingress/路由配置。
