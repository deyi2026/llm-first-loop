---
title: 冻结补丁候选→Host 准入→原版 R9 的三条操作纪律（核对/命令/还原）
scenario: 对 web-interaction r4 冻结候选（candidate-r4.patch，13 文件）先核对指纹与内容，再走 review_admission(kind=full_test) 独立审查，PASS 后在候选 worktree 跑 bash scripts/ci_gate.sh 全量。
root_cause: 三个易错点：假成功的 patch 应用校验、Host 准入对命令形态与一致性的硬约束、全量测试对跟踪产物的写入副作用。
solution: "1) 候选一致性用 blob 比对：解析 patch 的 \"index A..B\"，A 对 HEAD:path、B 对 git hash-object 工作树文件；不要用\"临时目录 git apply 后再比\"来验证——仓内子目录执行时曾出现返回 0 但实际未落盘的假成功，结论会错。2) review_admission 的 command 必须逐字为裸命令（bash scripts/ci_gate.sh）；带管道/复合（| tail、2>&1 | tail）会被 RULE-AI-28 以 compound_protected_shell_requires_split_commands 拒绝，且 R9 重试命令须与准入命令一致。3) ci_gate 全量 pytest 会重写 reports/ 下跟踪产物（时间戳/ID 差异），跑完 git checkout -- reports/ 还原，使 worktree 回到冻结的 13 文件态；再复验 13 文件 blob == patch 后像。"
evidence: "指纹 sha256=17095f40…25a95 / 28295B / 13 段；blob 校验 FILES 13 ALL_POST_IMAGE_MATCH（跑完 R9 后复验仍一致）；review_admission start frozen=b8d4c610…c57a → status PASS P0=0 P1=0；R9：五步全绿，11562 passed/177 skipped/276.88s，exit 0（evidence://v1/cb52ad8cc37fd68156a2697da414393b56488648ea7b61eedc7db60b1c64263b）；还原后 changed=13、HEAD 2894beda7 未变。"
tags: [review_admission, ci_gate, 候选冻结, blob校验, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-27T16:29:21.919579+08:00"
updated_at: "2026-10-27T16:29:21.919579+08:00"
---