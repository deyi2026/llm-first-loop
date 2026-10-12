---
method_id: probe-live-service-via-known-pid-not-guessed-endpoints-be8ae0d7582a
name: probe-live-service-via-known-pid-not-guessed-endpoints
description: 核验本机运行服务的实时声明（健康检查、监听端口、实时行为）时，探测目标必须从 trace 中已有的权威标识（pid、cmdline、配置绑定地址）导出，而不是凭常用端口/常见路径猜测。pid→lsof/ss 是确定性 provenance 边：一次调用给出确切 host:port；猜测失败（连接 000/404）多花一轮，且即使偶然命中也不构成可靠证据。本集先猜 8787/healthz 得到 000，随后对早已出现在版本核验结论中的 pid 47172 执行 lsof，立即得到 127.0.0.1:8903 并确认健康声明。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:0:926b7178cd0c9af8d2b0
evidence_refs: learning:learn:20740d57e6a0
created_at: 2026-10-13T04:12:14.426497+08:00
updated_at: 2026-10-13T04:12:14.426497+08:00
---
## Trigger
任务需要验证关于一个正在运行服务的实时状态声明（如"健康检查返回 200"、"某端口在监听"），且此时 trace 中已出现该进程的权威标识（pid、进程名、配置文件中的绑定地址）。

## Discriminator
能否从已有事实一步导出探测目标：已知 pid 时，OS 层（lsof/ss/netstat）或服务配置能确定性地给出监听 socket；凡不是由 pid/config 导出、而是按"合理默认值"拼出的 URL 都是猜测。本集发起 curl 8787/healthz 前，pid 47172 已在版本核验消息中出现，却未被用于解析端口。

## Short path
- 检查 trace 中已有的权威句柄：status/审计输出的 pid、进程名、runtime 配置的 bind 地址
- 已知 pid：执行 lsof/ss -p <pid> 取得确切 LISTEN 地址（未知量：服务实际绑定在哪）
- 对导出的 host:port 发起目标探测（如 /health），记录状态码与时间戳（未知量：健康声明真伪）
- 尚无句柄时，先用 pgrep/ps 或读配置低成本取得句柄，而不是直接猜 URL
- 探测结果确认或证伪待核验声明后即停止，进入审查结论

## Stop conditions
- lsof 输出已给出唯一 LISTEN 地址
- 针对该地址的健康/状态探测已确认或证伪待核验声明
- pid 无任何 LISTEN socket——这本身就是"服务未监听"的答案，无需继续枚举端口

## Verification
- 探测所用 host:port 与 lsof/配置输出逐字一致，不是猜测值
- 结论中引用的核验结果附带真实地址与时间戳（本集最终以 127.0.0.1:8903/health=200 为准）

## Counterexamples
- trace 中没有任何进程标识、也无配置可读：此时 ps/netstat 广扫就是正确的第一步，本方法的前置（已知句柄）不成立
- 服务是远程/受管部署（容器端口映射、代理、k8s service）：本地 pid 不映射到对外端点，应读部署清单/配置而非本机 lsof
- 待核验声明与实时端点无关（纯源码审计、文档核对）：不要为"看起来该验证"而发起进程探测
