---
title: search_files 定位深层文件：用绝对 root，相对 root 会失败
scenario: "用 search_files 按文件名定位工作区内深层嵌套文件（如 nested/deep/needle_target.txt）。不传 root 或 root=\".\" 时返回「无匹配」，但 find . -type f 能列出该文件；root=\"nested/deep\"（相对路径）直接报「目录不存在」。"
root_cause: ""
solution: 先用 execute_command 的 pwd 取得工作区绝对路径，再把该绝对路径作为 search_files 的 root（pattern 用裸文件名即可命中深层文件）。root 只接受搜索根目录、且需为绝对路径；查单个已知文件可用 root=<绝对父目录> + pattern=<文件名>，或 root=<绝对工作区> + path=<相对文件路径> 做精确 stat。定位失败时不要断言文件不存在，先用 find 交叉验证。
evidence: "同一会话内：search_files(pattern=needle_target.txt) 与 root=\".\" 均「无匹配」；find . -type f 输出 ./nested/deep/needle_target.txt；search_files(root=\"nested/deep\") 报「目录不存在」；search_files(root=/private/tmp/lfl-method-discoverability-weak-v01/locator_precall_method__off__r2/workspace, pattern=needle_target.txt) 命中 1 条 nested/deep/needle_target.txt；root=绝对工作区 + path=nested/deep/needle_target.txt 返回 stat 存在（14 字节）。"
tags: [search_files, tool-usage, file-locator, absolute-path]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-30T19:56:21.143093+08:00"
updated_at: "2026-09-30T19:56:21.143093+08:00"
---