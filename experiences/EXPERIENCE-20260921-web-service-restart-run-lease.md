---
title: Web 托管会话内发起 service restart 会自死锁于自身 run lease
scenario: 从 web 托管的 agent 会话内调用 service_control restart(target=all)，重启 worker 等待 admission barrier 900s 后超时失败
root_cause: restart 准入屏障要求 0 个活动 run.lock，但 web 托管会话的 run.lock 由待重启的 web 进程自身持有，构成结构性自死锁；且该锁在 run 结束后的空闲窗口仍未释放
solution: 物理重启需在 agent 会话外执行：操作者终端跑 scripts/restart_mirror.sh，或先关闭所有 web 托管会话使 run lease 释放后再发起官方 restart；会话内重试 restart 只会重复 900s 超时
evidence: data/runtime/service-control-actions/svc-6f43056ad30b47abae4c8c619307676a.json; data/runtime/service-control-actions/svc-81839c8cb1264619989435ebdee3c4e2.json; lsof 输出（pid 11277 持有 6e0fb83b…run.lock，fd 7w）; data/restart-receipt.json（web_pid=11277）; data/service-control-worker.log（无 gen60 重启记录）
tags: [service_control, restart, admission_barrier, run_lock, self_deadlock]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-21T04:50:11.362375+08:00"
updated_at: "2026-09-21T04:50:11.362375+08:00"
---

2026-09-21 gen60 发布后两次 service_control restart(all, gen60) 均失败。证据：data/runtime/service-control-actions/svc-6f43056ad30b47abae4c8c619307676a.json 与 svc-81839c8cb1264619989435ebdee3c4e2.json 均 status=failed，detail="target still busy after 900s: active run locks: 1"。lsof 证实唯一被持有的 run.lock（会话 6e0fb83b）由 web 服务进程 pid 11277 持有——即承载发起 restart 会话的进程本身。且失败时刻 20:27:35 落在无 run 空闲窗口（最后 run 20:12:34 结束），证明"结束当前 run 即放行"不成立（lease 超出 run 生命周期或 web 侧周期性占用）。可行落地路径：在 agent 会话外由操作者执行 scripts/restart_mirror.sh（gen58/59 均经此路径成功，见 data/service-control-worker.log 与 data/restart-receipt.json），或先关闭 web 会话再走官方 restart。