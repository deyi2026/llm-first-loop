---
title: 审稿子代理在本工作区跑仓库级命令会 60s 超时，改用静态读数回执离线核对并令回执走最终回复正文
scenario: 把 LFL 推广稿交两名独立子代理做内容审稿，子代理按任务书用 execute_command 跑 git rev-list / find src/llm_loop / 全仓 grep 取证
root_cause: ""
solution: 三步收口：① 父会话先把真实命令与输出落盘成静态读数回执文件（如 receipts/d58-lfl-static-readings.txt），子代理离线读它核对，不自己跑仓库级命令；② 派单时明令「不要对整个仓库做 find/grep/git（会 60s 超时），只针对具体路径」，并把「停止并直接给结论」写成可执行的收尾指令；③ 不让子代理写回执文件，改要求把回执 JSON 直接放进最终回复正文，由父会话代落盘到 receipts/，避免「审稿跑完但没落盘」的空转。
evidence: docs/promotion/receipts/daily58-content-review.json、docs/promotion/receipts/daily58-content-review-b.json（两份回执均由子代理最终回复正文代落盘）、docs/promotion/receipts/d58-lfl-static-readings.txt（父会话落盘的真实命令与输出）
tags: [子代理, 审稿, 超时, 静态读数回执, 执行面]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T09:20:44.973540+08:00"
updated_at: "2026-11-04T09:20:44.973540+08:00"
supersedes: [EXPERIENCE-20261025-子代理文件工具作用域-仓库-跨域写代码必须走-execute-command-workdir-rep]
---