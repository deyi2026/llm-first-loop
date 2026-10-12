---
title: Fleet 最小纵切五步法：机制优先、manifest 随基线、live 隔离 harness 收尾
scenario: 为 LFL 新增 fleet 执行平面并要求机制测试+真实子代理 live 验证双重闭合
root_cause: ""
solution: 纵切顺序：纯机制→runner 注入→跨进程恢复→live 隔离 harness。每步 RED 回归先行、A.5 manifest 随基线同步、本地预跑门禁、独立 commit。
evidence: "PR #36 (fleet live qualification, spawn 13/13 + recover 5/5)；docs/QUALIFICATION-20260919-fleet-live-spawn-reclaim.md；slice commits 23ba6811..1c9856264 on main"
tags: [fleet, worker-lease, vertical-slice, live-qualification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T12:18:39.419999+08:00"
updated_at: "2026-09-19T12:18:39.419999+08:00"
---

背景：Project/ExecutionWorkspace/WorkerLease/reclaim 最小纵切需要从零 schema 起步并在 3 天内完成 5 slice 的真实模型 live qualification。做法：slice1 纯机制（ProjectStore+Lease/Reclaim+Fence，RED→GREEN）；slice2/3 runner 注入与跨进程 parent_of 恢复，每次基线更新同步 manifest 并本地预跑 A.5（base...head 差集含未申报路径即红，预跑消除 CI 假红）；slice4/5 FencedError 旧代拒写+parent-bound facts；收尾用隔离 harness（临时状态目录）跑真实 glm-5.3 spawn 13/13 + recover 5/5，失败历史全量写入 QUALIFICATION 文档。教训：live 验证的 provider 悬挂与 harness 自身 bug 必须如实入档，只写结论不可信。