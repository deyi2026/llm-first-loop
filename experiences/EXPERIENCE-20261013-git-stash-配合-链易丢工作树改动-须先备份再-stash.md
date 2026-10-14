---
title: git stash 配合 && 链易丢工作树改动，须先备份再 stash
scenario: "想验证\"新测试在没有修复时确实会失败\"，用 git stash push 临时还原源码、跑测试、git stash pop 恢复。结果 pop 因命令链提前退出被跳过，改动从工作树丢失。"
root_cause: "命令写成 A && B; C 的形式时，前段非零退出（如 stash push 与 pop 之间某命令 fail_fast 中断）会跳过后续 pop，改动滞留在 stash 里，工作树呈现为\"被还原\"的状态且无明显提示。"
solution: stash 前先 cp 到 /tmp 备份；stash 后无论是否恢复成功，都用备份 cp 回并 diff -q 核对；确认临时 stash 只含本次文件后再 drop。验证完务必核对 grep 标记行数与 git diff --stat 确认改动在位。
evidence: 实测：修复一度从工作树消失（grep -c 标记行=0，git diff --stat 只剩测试文件）；用 cp /tmp/validator_fixed.py 还原后 diff -q 输出 IDENTICAL，标记行=2，diff --stat 恢复为 2 文件 +49/-5。
tags: [git-stash, 工作树安全, 回归验证, 失败注入]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T22:01:18.356456+08:00"
updated_at: "2026-10-13T22:01:18.356456+08:00"
supersedes: [EXPERIENCE-20260917-git-stash-pop-pytest-60s-stash]
---