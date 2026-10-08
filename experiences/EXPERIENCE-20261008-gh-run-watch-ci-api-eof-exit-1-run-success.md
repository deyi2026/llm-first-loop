---
title: gh run watch 退出码非 CI 结论：瞬时 API EOF 致 exit=1 而 run 实为 success
scenario: 后台委派 `gh run watch <id> --exit-status > log 2>&1; echo exit=$?` 监听远端 CI run，收尾回执 exit=1，与 CI 实际结论冲突，需判定走修复分支还是收口
root_cause: ""
solution: "watch 退出码 ≠ run 结论：`gh run watch` 自身轮询 GitHub API 时发生瞬时传输错误（unexpected EOF）即以非零退出，即使 run 最终 success。判定权威 = run 完成后全新 `gh run view <id> --json status,conclusion` / `gh run list`；watch 的 exit=1 先查其日志尾部是否为传输层报错再定分支。"
evidence: /tmp/gh_watch_37756434733.log 尾部 unexpected EOF；job-517e9dab282b40a2bae1 exit=1；gh run view 37756434733 completed/success；gh run list 复核 success 9m27s
tags: [github-cli, ci-watch, exit-code-semantics, delegation]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-08T17:34:47.967903+08:00"
updated_at: "2026-10-08T17:34:47.967903+08:00"
---

gh run watch 37756434733 --exit-status 后台委派报 exit=1，但同刻 gh run view 显示 conclusion=success。日志尾部实证：`failed to get run: Get "https://api.github.com/.../runs/37756434733?exclude_pull_requests=true": unexpected EOF`——是 watch 轮询的 API 传输层瞬断，不是 run 失败。收口判定应以 run 完成后的全新 `gh run view <id> --json status,conclusion`（或 gh run list）为准；watch 退出码仅作线索。惯例：委派 watch 命令照旧 `> log 2>&1; echo exit=$?` 落档，见红先查日志尾部传输错误再定分支。