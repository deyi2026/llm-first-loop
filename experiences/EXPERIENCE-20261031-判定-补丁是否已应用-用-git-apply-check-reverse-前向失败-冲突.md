---
title: 判定「补丁是否已应用」用 git apply --check --reverse，前向失败≠冲突
scenario: "交接文档要求把一份 canonical 补丁应用到工作区，用户执行 git apply 报 \"patch does not apply\"，看似上下文冲突；若照直觉再去改补丁或重做回填，会白跑并可能破坏已落盘内容。"
root_cause: ""
solution: "先跑反向检查：git apply --check --reverse <patch>。通过=补丁已完整应用，前向失败只是重复应用，正确动作是停手并核对目标文件是否已含新增章节（grep + mtime + git diff --stat），而不是改补丁。本例：反向 check 通过，设计书已 916 行（对 HEAD +190），§11.8/附录B/B.5 均在，两份文档 mtime 15:53，回填已在。"
evidence: "本次实测：前向 git apply --check 失败；反向 git apply --check --reverse 通过；工作区两份文档 mtime 均 15:53 且新增章节 grep 命中；git diff --stat 显示设计书 +190 行。命令与回执见 evidence://v1/8e954576766a506b6bc44c0194391fd0219e66b9dcf3902a9b82d758eb4a6385。"
tags: [git, patch, 交接, 验证纪律, workspace-backfill]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T16:02:25.860730+08:00"
updated_at: "2026-10-31T16:02:25.860730+08:00"
supersedes: [EXPERIENCE-20261031-git-apply-在仓库子目录内会静默忽略路径并返回成功-校验必须在仓库外做并逐条-grep-新章]
---