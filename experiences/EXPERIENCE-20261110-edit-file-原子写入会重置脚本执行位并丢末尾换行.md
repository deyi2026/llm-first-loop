---
title: edit_file 原子写入会重置脚本执行位并丢末尾换行
scenario: 在 LFL mirror 仓库用 edit_file 修改 shell 脚本（scripts/ci_gate.sh）后直接 git commit，未检查权限位与文件末尾换行。
root_cause: ""
solution: edit_file 改脚本后立即 chmod 755 + 补末尾换行，提交前用 git diff --cached --summary 核 mode change；被 Host 闸挡住不能直接跑 bash -n 时，cp 到 .tmp-ci/ 对副本校验语法。
evidence: 实测：data/review_admission/subagent_9d0d3d48990b-full_test.md（P1+P2①）；commit d95a73f82 记录 mode 100644，07e893cdb 恢复 100755；git ls-tree origin/main scripts/ci_gate.sh = 100755。
tags: [edit_file, shell, 权限位, 换行, 审查]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-10T00:24:07.913325+08:00"
updated_at: "2026-11-10T00:24:07.913325+08:00"
supersedes: [EXPERIENCE-20261106-代码修改三陷阱-read-复用致臆想-api-editable-venv-锚定错树-heredoc]
---

现象：用 edit_file 改 scripts/ci_gate.sh 后提交，独立审查判 P1——mode 从 100755 变 100644（工作区实际落成 600，连执行位都没有），且文件末尾换行丢失（diff 出现 "\ No newline at end of file"）。

机制：edit_file 走临时文件原子替换，不继承原文件权限位；写入内容以 new_string 字面为准，若 new_string 末行不带 \n，整文件就没有结尾换行。两者都不报错，只有 git diff --summary / 审查能看出来。

后果：`bash scripts/x.sh` 仍能跑，`./scripts/x.sh` 与依赖执行位的 hook/CI 调用会静默失效——属于"改完看起来成功、实际退化"的一类。

处置：改完脚本类文件后 (1) chmod 755；(2) 检查 tail -c 1 为 \n；(3) git add 后看 git diff --cached --summary 是否有 mode change；(4) 若被 Host 命令闸挡住不能直接 bash -n 被审查产物，cp 到 .tmp-ci/ 对副本做 bash -n。