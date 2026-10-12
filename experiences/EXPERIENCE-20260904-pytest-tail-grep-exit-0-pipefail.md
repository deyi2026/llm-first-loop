---
title: pytest 经管道转 tail/grep 后 exit=0 假绿：验证命令必须 pipefail
scenario: 后台 job 用 `pytest -q | tail -5` / `| grep -c FAILED` 跑全量单测，用于批次验证收口判定（镜像区 R8.24-B）
root_cause: execute_command 后台任务的 exit code 取自管道末端 tail/grep（恒 0），且 tail -5 截断使末行无汇总行，进一步掩盖失败规模
solution: 验证命令一律 `set -o pipefail` 并回显 pytest 原生退出码：`set -o pipefail; python -m pytest tests/unit -q; echo EXIT=$?`。判定全绿以 pytest 自身退出码+汇总行为准，不信 job 状态的 exit=0。本次实测：job-3 状态 done+exit=0 但实际 58 failed（job-5 grep 复核）。
evidence: "本会话 job_output(job-3/job-5) 实测：done+exit=0 与 58 FAILED 并存；GOAL-20260829-afd095ab checkpoint #4"
tags: [testing, shell, ci, verification, pipeline]
source: {}
status: active
created_at: "2026-09-04T13:32:04.570124+08:00"
updated_at: "2026-09-04T13:32:04.570124+08:00"
---

1) 后台测试任务命令必须 set -o pipefail 或不用管道；2) exit=0 只在 pytest 原生退出时可信；3) 后台验证任务优先保留完整输出（tee 全量日志），摘要靠事后 grep。