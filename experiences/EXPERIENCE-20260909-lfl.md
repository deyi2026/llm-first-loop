---
title: LFL 环境：后台任务不跨会话存活 + 长测试套件需分片前台执行
scenario: "llm-first-loop 运行环境：需要执行长于单轮工具超时（60s）的大套件 pytest 或长命令，且可能中途被\"继续\"唤醒新会话轮次。"
root_cause: execute_command 后台任务的存活域是当前真人 run，会话结束即收割；前台超时（默认 60s）同样杀进程组。
solution: a) 长任务不用 run_in_background（收割风险）改前台；b) 超预算套件按测试文件字母序 split -l N 分片（BSD split 无 -n，用 -l），每片独立执行各留日志，片粒度按总时长/N 且留一倍余量（本例 398 文件 / 全量≈150s → 80 文件/片×5）；c) 结果同时落盘 /tmp/*.log 防轮次丢失；d) 本仓库 pytest 摘要行被自定义插件吞掉，判定用 EXIT 码 + grep -cE '^FAILED'，别 grep passed/failed。
evidence: "job_output kill 记录×2；/tmp/cr_r1_full_regression3.log 7.8KB/18KB 截止于 16:19，pgrep 无 pytest"
tags: [environment, background-job, pytest-chunking, lfl-runtime]
source: {}
status: active
created_at: "2026-09-09T16:25:01.370457+08:00"
updated_at: "2026-09-09T16:25:01.370457+08:00"
---

复现两次：job_output 显示 killed+cancel_requested、日志残缺或不存在。即使 execute_command 前台超时被杀，pytest 进程组也会随之死亡（pgrep 证实）。