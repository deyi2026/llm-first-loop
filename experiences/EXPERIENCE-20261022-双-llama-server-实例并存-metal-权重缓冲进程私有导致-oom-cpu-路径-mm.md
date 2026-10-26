---
title: 双 llama-server 实例并存：Metal 权重缓冲进程私有导致 OOM；CPU 路径 mmap 共享页可并存
scenario: 在本机（128GB 统一内存）已有生产 llama-server（-ngl 999 全 GPU，模型 ~82GB）运行时，试图在隔离端口再起一个同模型 llama-server 做审计/补测
root_cause: ""
solution: 三选一：① 用户授权后 lfrt stop --yes 临时停生产、隔离实例独占 GPU 跑、完成后 lfrt start 恢复（本轮采用，与 V22 GPU profile 一致性最强）；② 隔离实例 -ngl 0（CPU 后端读 mmap 共享干净页，可与生产并存，但后端偏离 GPU profile，需如实标注）；③ 换更小模型（改变审计对象，需授权）。不要在未停生产时直接 -ngl 999。
evidence: analysis/determinism_audit_E1_20261022/RECORD.md §2 偏差③；server_8905.stderr.log（GPU OOM 三连错误行）；launch_err.log（-L invalid）；job-ac3145a6c33f4a1285d1 e1_result.json（恢复后 PASS）
tags: [llama-server, metal-oom, mmap, isolated-port, lfrt]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-22T09:07:26.381250+08:00"
updated_at: "2026-10-22T09:07:26.381250+08:00"
---

同一 llama-server 大模型（82GB）双实例并存时 Metal 报 kIOGPUCommandBufferCallbackErrorOutOfMemory（/completion 500、后端进入错误态需重启）；权重经 mmap 只读加载时干净文件页跨进程共享，-ngl 0 可与生产并存启动。操作坑：本 fork (465e49b9) llama-server 无 -L 旗标（invalid argument 秒退，stderr 必须落盘否则难归因）；macOS 无 setsid；execute_command 前台命令 60s 超时但 nohup+重定向的后台进程可存活，长任务用 run_in_background。诊断顺序：先看 stderr 再猜工具行为。