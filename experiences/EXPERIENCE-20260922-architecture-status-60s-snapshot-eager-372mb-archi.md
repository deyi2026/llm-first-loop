---
title: architecture_status 60s 超时根因：snapshot eager 全量构建 + 每次 372MB archive 解析被瞬时负载放大（自愈型，非挂死）
scenario: "LFL 运行时 architecture_status 工具间歇性 60s 超时（21:30 与 21:58-22:01 两个窗口，之后自愈），search_files 在相邻窗口亦超时；需要区分「参数/维度问题」vs「负载/调度问题」。"
root_cause: ""
solution: 不要按参数逐个排查维度（参数矩阵会全部矛盾）；直接读 session event_log 的 tool.execution.started/finished 拿服务端真实耗时分布（正常 7.1-7.6s vs 异常 52-61s+），再对可疑组件做独立进程计时（python3 -c 复现解析成本），并核对 registry 超时=放弃等待的僵尸线程语义。结论：超时是「eager 全量构建 + 每次 372MB archive 解析 + 瞬时负载放大」的组合，非挂死、非特定维度、非 lfrt。
evidence: "event_log timing: 13:39:44→13:40:45 timeout 60.7s; 13:58:51→13:58:59 success 7.6s; 14:00:46→14:01:47 timeout 61.0s; 14:02:23×2→14:03:24 timeout 61.3s; 14:04:08×2→14:05:01 success 52.2s; 14:05:39→14:05:46 success 7.2s; 14:06:09→14:06:16 success 7.1s; 14:09:13→14:09:20 success 7.3s（同一 combo 参数先超时后原样重试成功）。代码：status.py L557-730（eager 构建）、L592-616（causality/local_runtime 惰性）、memory/archive.py L690-710 stats 全量解析；lfrt_runtime.py L449-460 timeout=2.0；registry.py L1455-1479 超时放弃语义。独立实测：archive jsonl 解析 3.05s/372MB；inspect_knowledge_health 0.01s。"
tags: [architecture_status, timeout, performance, diagnosis, event_log, LFL运行时]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-22T22:14:30.588323+08:00"
updated_at: "2026-09-22T22:14:30.588323+08:00"
---

现象：architecture_status 连续 60s 超时（含最小维度调用）。已排除：lfrt CLI 观察器（subprocess.run timeout=2.0s fail-closed）、knowledge_health（独立进程实测 0.01s）、causality（session event log 仅 1.67MB；非 causality 维度惰性不触碰 1.9GB event_logs）、search_files 同窗口超时为独立问题（21GB 全区扫描本身重）。根因链：① snapshot() 先全量构建全部维度后才按 dimensions 过滤（status.py L641-718），单维度调用也付全价；② 最重组件 _sum_archive_stats 每次调用全量解析 data/archives 139 个 jsonl（372MB，独立实测 3.05s），单次基线 ~7s；③ 负载波动放大：两个并发只读池调用实测 52.2s 贴线、61s+ 超时；系统级负载（web 重启、search_files 僵尸线程、LLM 流式+extract 高频 IO）进一步压缩可用资源。④ registry 超时语义：60s TIMEOUT 只是放弃等待，非 daemon 工作线程继续跑到自然结束（registry.py L1455-1462 明示），故一次超时常伴连续多次超时后突然全部恢复（自愈，勿误判为已修复）。诊断手段：session event_log 的 tool.execution.started/finished 事件含精确服务端耗时（tool.execution.finished status=timeout/success），比客户端超时回执信息量大得多。候选修复（未授权执行）：snapshot 按 dimensions 惰性构建；_sum_archive_stats 增量化/缓存；或利用 registry_timeout_s per-tool opt-out 给 architecture_status 放宽超时。