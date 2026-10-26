---
title: lsof -p PID -i 是 OR 关系不是 AND，必须用 -a
scenario: 排查某进程的网络连接时用 `lsof -nP -p 11048 -i`，输出全是无关进程的连接，差点误判目标进程无网络连接。
root_cause: lsof 未显式指定 -a，选择器按 OR 合并；且管道中前一条命令的非零退出码触发 fail_fast 提前结束，导致只看到部分输出。
solution: lsof 的多个选择器之间默认是 OR：`lsof -p X -i` = (进程为 X) OR (有网络连接)，会列出全系统。必须写 `lsof -nP -a -p X -i`（-a 强制 AND）。另外本环境 fail_fast 下 grep -c 无匹配返回 1 会中断管道，多条统计命令需 `|| true` 保护。
evidence: 2026-10-15 实测：`lsof -nP -p 11048 -i` 退出码 141 且输出 31 行含 python3/ControlCe/winkstock 等无关进程；改用 `lsof -nP -a -p 11048 -i` 后正确返回 AweSun 11048 的 2 个 UDP + 1 条 TCP ESTABLISHED。
tags: [lsof, shell, 命令正确性, 排障]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-15T19:30:25.890526+08:00"
updated_at: "2026-10-15T19:30:25.890526+08:00"
---