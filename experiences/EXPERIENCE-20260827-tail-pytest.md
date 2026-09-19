---
title: 管道日志退出码陷阱：$? 取的是 tail 而非 pytest
scenario: execute_command 后台任务跑测试套件、管道落日志、依据退出码判断回归
root_cause: "bash 管道中 $? 取最后一个命令（tail）退出码，pytest 的真实退出码需 PIPESTATUS[0]"
solution: "管道后记录 ${PIPESTATUS[0]}（或 set -o pipefail）；日志窗口保留 pytest 统计行；FAILED 行 grep 独立确认"
evidence: ""
tags: [bash, pipestatus, pytest, ci-logging, exit-code]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
created_at: "2026-08-27T18:37:09.132929+08:00"
updated_at: "2026-08-27T18:37:09.132929+08:00"
---

后台跑测试并落日志：`pytest tests/unit -q 2>&1 | tail -20 > log; echo "exit=$?" >> log` —— $? 是 tail 的退出码（恒 0），不是 pytest 的。实际案例：全量 2 个 FAILED 但日志尾部 pytest_exit=0，险些误判零回归放行。正确写法：echo "pytest_real_exit=${PIPESTATUS[0]}"（bash）；或 set -o pipefail。同类陷阱：tail -N 截掉 pytest 的 "X failed, Y passed" 统计行时，仅凭 exit 码不可靠——日志里应保留统计行（tail 窗口给够）并以 PIPESTATUS 为准。