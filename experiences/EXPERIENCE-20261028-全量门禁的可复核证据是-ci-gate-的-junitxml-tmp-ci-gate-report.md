---
title: 全量门禁的可复核证据是 ci_gate 的 junitxml（/tmp/ci_gate.*/report.xml），不是 stdout；包装命令会被准入拒绝
scenario: 需要为「全量门禁在某 commit 上绿了」提供可独立复核的落盘证据（CI/合并闸审查者不认口头复述与只存在于工具回执的 stdout）
root_cause: ""
solution: ci_gate.sh 本身把全量 pytest 结果写到 mktemp 目录下的 $GATE_XML（/tmp/ci_gate.XXXXXX/report.xml），这就是程序自产、可离线解析的合规证据：跑完立刻复制到证据目录并记录 tests/failures/errors/skipped/timestamp/sha256，再用「passed 数与旧 tip 的差值 = 本轮新增测试条数」做交叉验证。注意两条硬约束：受保护命令（全量 pytest/ci_gate.sh）禁止 shell 重定向；review_admission 只接受裸命令，用 script/tee 包装会以 review_kind_command_mismatch 被拒，所以不要指望 stdout 文本日志落盘。
evidence: "/tmp/ci_gate.MIr07r/report.xml 解析 tests=12004 failures=0 errors=0 skipped=174 timestamp=2026-10-28T15:55:55+08:00，sha256=00f268e7b4f3c8b7f1c816c221b540d8e7d9a84e9bdc1c16560f504bd393b31c（evidence://v1/ef779a911a1c0a60deb6e2e3958529854f5f9ffc48c5a4953d82cf688cc323c1）；ci_gate.sh 第 139 行 --junitxml=\\"$GATE_XML\\"；review_admission 以 command=\\"script -q ... bash scripts/ci_gate.sh\\" 请求被拒 reason=review_kind_command_mismatch"
tags: [ci_gate, junitxml, evidence, review_admission, full-test]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T16:33:36.462821+08:00"
updated_at: "2026-10-28T16:33:36.462821+08:00"
---