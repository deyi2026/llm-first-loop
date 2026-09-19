---
title: llm-first-loop-mirror 仓库 origin 指向 legacy 仓库，真实远端是 lfl
scenario: "在 /Users/yyj/Project/llm-first-loop-mirror 做任何 git/gh 远端操作时：git remote -v 显示 origin=https://github.com/deyi2026/llm-first-loop-legacy.git（9 月 9 日后不再更新），而真实活跃仓库是 lfl=https://github.com/deyi2026/llm-first-loop.git。gh CLI 的默认仓库解析也落在 legacy。2026-09-17 用 ls-remote origin 和 gh api 检查 main 时误判为\"远端 main 被回退到 9 月 9 日、PR #24 消失、分支保护关闭\"，实际是查错了仓库；随后 git fetch origin 还因 legacy 仓库网络慢而超时。"
root_cause: ""
solution: "远端操作一律显式指向 lfl：git ls-remote lfl / git fetch lfl；gh 操作显式 -R deyi2026/llm-first-loop（如 gh pr view 24 -R deyi2026/llm-first-loop）。判断\"远端是否回退/异常\"前先 git remote -v 核对当前查询的 remote 身份；origin/main 跟踪 ref 停在 2026-09-09 属正常（legacy 早已停更），不是回退信号。"
evidence: "git remote -v 输出（origin=legacy, lfl=llm-first-loop）；git ls-remote lfl refs/heads/main = bb59de20；gh repo view --json nameWithOwner = deyi2026/llm-first-loop-legacy；origin/main reflog 最后更新 2026-09-09 05:33 \"update by push\"=a4c9f21d"
tags: [git, remote-configuration, false-alarm, llm-first-loop, gh-cli]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T17:43:07.042668+08:00"
updated_at: "2026-09-17T17:43:07.042668+08:00"
---