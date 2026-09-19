---
title: macOS 本地 MLX 大模型多会话变慢：并发参数限制是根因，launchd 化+4/4 并发修复
scenario: macOS 上 mlx_lm.server 托管 35B MoE 模型（如 Ornith-1.5-35B-A3B-MLX，8901 端口）时，两个以上会话同时访问速度急剧变慢，多路并发请求分波串行完成。
root_cause: "mlx_lm.server 的 prompt/decode 并发批处理上限参数设为 2，多会话请求超出即排队，表现为\"两个以上会话特别慢\"。非内存不足、非模型切换。"
solution: 1) 根因：启动参数 --prompt-concurrency 2 --decode-concurrency 2 把 prompt 处理和解码批上限锁在 2，超出即排队串行。2) 修复：并发调至 4/4（35B 模型 rss ~65GB，128GB 机器上 4 路并发是内存带宽安全上限，不建议更高）。3) 持久化：launchd 托管（plist + LaunchAgents 软链），关键配置 ExitTimeOut=30（优雅退出宽限）、KeepAlive 节流 30s（崩溃自愈）、RunAtLoad（登录自启）。4) 运维脚本 control.sh 提供 status/stop/restart，restart=bootout→等端口释放(≤15s)→从软链 bootstrap 全量重载读最新配置。5) 验证方法：4 路并发短生成应同时完成不分波；就绪判定轮询 /v1/models 最多 240s（35B 权重加载 1-3 分钟）。
evidence: /Users/yyj/Project/research/runtime/launchd/local.mlx.qwen8901.plist（--prompt-concurrency 4 --decode-concurrency 4）；qwen8901-control.sh；2026-09-11 多开测试实测：4/4 下 5-7 并发会话仅部分排队（active 峰值 7），16tok 延迟探针 1.3s，swap 持续回收 15.4G→9.3G，模型 rss 65GB 稳定无重载。
tags: [mlx, mlx_lm.server, concurrency, launchd, macos, local-llm, multi-session, performance]
source: {}
status: archived
archived_at: 2026-09-18
archived_reason: lifecycle-batch1: invalid 标记收尾（已判失效，归档保留全文可追溯）
created_at: "2026-09-11T14:01:58.229608+08:00"
updated_at: "2026-09-11T14:11:48.717151+08:00"
---