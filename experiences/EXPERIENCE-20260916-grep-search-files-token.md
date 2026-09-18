---
title: 本工作区代码检索须用 grep，search_files 内容搜索对下划线 token 假阴性
scenario: "在 llm-first-loop 工作区用 search_files(content=...) 检索下划线 token（如 task_anchor_pin_messages、pinned_msg_seqs）返回\"无匹配\"，但符号确实存在于 src/ 且 git diff HEAD 为空（工作区=HEAD）。"
root_cause: ""
solution: 代码符号检索一律用 execute_command grep -rn；search_files 的 content 匹配对下划线连写 token 有假阴性，只适合文件名/路径类检索。裸 python 解析 llm_loop 也会落到 .worktrees 旧副本（editable 安装指向），需显式 PYTHONPATH=src。
evidence: "evidence://v1/f0a030b02c686825e3408eafad951709d6b990482f470232fdaf5c45839cb4b2 evidence://v1/03f794bdc6bddb9d60f9c9cf4c4b12247a54cfa29e5d34cd00c7df2c5049f119"
tags: [workspace, search, tooling, verified]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T16:16:29.786960+08:00"
updated_at: "2026-09-16T16:16:29.786960+08:00"
---