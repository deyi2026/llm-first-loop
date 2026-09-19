---
title: 本地 LLM 服务监控排障坑清单：旧 Traceback 误判、HTTP 层异常非崩溃、暖机与 swap 回收节奏
scenario: 对本地 mlx_lm.server 做健康监控与异常排障时，容易把正常现象误判为故障，或漏看真正的排队/重载信号。
root_cause: 本地推理服务的日志时间跨度长（含历史错误）、慢启动、内存回收异步、大 prompt 处理期长，且排障时容易把设计内排队当作故障。
solution: "七条坑及对策：1) stderr 日志里的 Traceback 必须带时间戳过滤——数天前的旧错误（如 9-08 的 mlx.core AttributeError）会混在同文件里，grep 'ERROR|Traceback' 不加时间过滤必误判。2) socketserver 'Exception occurred during processing of request' 是客户端断开流式连接触发的 HTTP 层异常，非模型崩溃，不要据此重启；判定标准是服务是否继续返回 200 + 探针延迟。3) 重启后 35B 权重加载 1-3 分钟，且首请求要暖机（大 prompt 处理可能 >30s），用 /v1/models 轮询就绪 + max_tokens=16 短探针（curl -m 55）做基线。4) swap 回收是缓降过程（9.5G→9.3G 历时数十分钟），不要期望 kill 后立即恢复。5) 'Prompt processing progress: N/16062' 持续滚动是 16k 大 prompt 正常处理（约 17s），不是卡死。6) active sequences > 并发上限 = 排队信号，属设计容量行为；配合 reqs/min 与延迟探针趋势判定，单点超限不算故障。7) 周期监控接力用 schedule(wake=true) 时注意：委派链无法自举（报 'ingress 不可委派：必须是未委派的真实 human ingress'），真实 human ingress 一次唤醒后方可续注册，接力监控需用户真实消息桥接。"
evidence: /Users/yyj/Project/research/runtime/logs/qwen8901.stderr.log（128/137 行 2026-09-08 旧错误 vs 864-870 行当前 HTTP 层异常）；monitor8901_20260911_121904.log（205 采样点：active 峰值 7、swap 15.4G→9.3G、reqs 非零 46 次）。
tags: [mlx, monitoring, troubleshooting, false-positive, swap, warmup, traceback, schedule, launchd]
source: {}
status: active
created_at: "2026-09-11T14:01:58.233843+08:00"
updated_at: "2026-09-11T14:01:58.233843+08:00"
---