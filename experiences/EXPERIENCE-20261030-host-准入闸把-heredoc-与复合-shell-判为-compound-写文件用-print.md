---
title: Host 准入闸把 heredoc 与复合 shell 判为 compound：写文件用 printf 单段、测试用显式单段路径
scenario: 连续三次命令被 RULE-AI-28 拦截，理由 compound_protected_shell_requires_split_commands：一次是 heredoc+git add+git commit，一次是 heredoc 单独，一次是 ls+pytest+pytest 的复合。
root_cause: 准入闸对 shell 命令做分段解析，heredoc 体与多段串联被判为 compound，无法绑定审查目标。
solution: 1) 用 execute_command 的 workdir 参数代替 `cd X &&`；2) 写文件不用 heredoc，改 `printf '%s\n' '行1' '行2' ... > file`（整条命令写成一行，无换行、无串联）；3) pytest 用单段命令 + 显式文件路径（不要用 `$(...)` 或多段拼接）；4) `git push` 必须是独立的单段命令，核验另起一条。文件内容里出现本机绝对路径还会触发 git_security_scan 的绝对路径闸，写文档时用 `/Users/<user>/...` 之类占位形式。
evidence: "三次 compound_protected_shell_requires_split_commands 拦截（heredoc+add+commit / 纯 heredoc / ls+pytest+pytest）；改为 workdir + printf 单段后写文件成功，pytest 单段显式路径成功（141 passed, 1 skipped），git push 单段成功"
tags: [准入闸, compound, printf, workdir, heredoc]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T14:45:46.415119+08:00"
updated_at: "2026-10-30T14:45:46.415119+08:00"
---