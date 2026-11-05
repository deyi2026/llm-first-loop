---
title: 长时 Python 渲染放后台时，管道缓冲导致进度全不可见
scenario: 用 execute_command 跑分钟级 Python 渲染脚本（1440x960 4spp，实际 355s），脚本每 pass 有 print 进度。直接前台调用 60s 超时；改 run_in_background 后 job_output 连续 240s 显示「输出 0 行」，误以为卡死或静默失败。
root_cause: 命令带 `2>&1` 使 stdout 变成管道，Python 默认对非 tty 输出做块缓冲（约 8KB）。每个 pass 一行进度远小于缓冲区，全部积压到进程退出才刷出。所以「无输出」不代表无进展，也不代表失败。
solution: |
  1) 超过 ~60s 的任务一律 run_in_background=true，再用 wait(job_id=...) 等终态，不要在前台硬跑。
  2) 需要看实时进度时加 `python3 -u` 或 `PYTHONUNBUFFERED=1`；只想拿最终结果则不必，照常等 job_terminal + exit code。
  3) 判活不要依赖 job_output 的行数，看 state；最终以 exit code 与产物文件（存在性+尺寸+内容统计）为完成依据，不以「没报错」为准。
  4) 产物可复现性用 sha256 比对两次运行的输出，逐字节相同即证明确定性和无漂移。
evidence: "本轮实测：job-214c93d89d4f4fbf80f3 前 240s job_output 恒为「输出（0 行）」且 state=running；终态 exit=0 后一次性刷出 6 行（含 4 个 pass 计时 47.9/136.0/223.9/313.1s 与 \"wrote live_run.png ... in 355.6s\"）。产物 live_run.png 与 pelican_bicycle.png 的 sha256 同为 16cd4f7443fb11e70bac990d1ee1b1f8033421ebc5d73abd1c069ce4986575fe。"
tags: [execute_command, 后台任务, stdout缓冲, 渲染, 完成判据]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T22:28:09.614871+08:00"
updated_at: "2026-11-04T22:28:09.614871+08:00"
---