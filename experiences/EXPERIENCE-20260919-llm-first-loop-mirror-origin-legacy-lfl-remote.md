---
title: llm-first-loop-mirror 的 origin 指向 legacy 仓库，推送须用 lfl remote
scenario: 在 /Users/yyj/Project/llm-first-loop-mirror（含 .worktrees/* worktree）向 GitHub 推送 feature 分支
root_cause: ""
solution: 推送前先 `git remote -v` 确认目标 remote 名；本仓库真仓库是 `lfl`（deyi2026/llm-first-loop.git，PR/CI 所在），`origin` 是 legacy 仓库（llm-first-loop-legacy.git），`mainrepo` 是本地 mirror 自身。分支的 upstream 也可能未设置，不能依赖默认 push 行为。混排输出（push 错误 + ls-remote 空）时逐条单跑重验，别下结论。
evidence: "git remote -v 回执：origin=https://github.com/deyi2026/llm-first-loop-legacy.git，lfl=https://github.com/deyi2026/llm-first-loop.git；ls-remote origin refs/heads/fleet-reclaim-fence-20260919 返回空（exit 0）；git push lfl 回执 5e4b2a74d..2a6817613 快进 exit 0"
tags: [git, remote, push, mirror, worktree]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T15:56:44.137036+08:00"
updated_at: "2026-09-19T15:56:44.137036+08:00"
supersedes: [EXPERIENCE-20260917-llm-first-loop-mirror-origin-legacy-lfl, EXPERIENCE-20260911-llm-first-loop-mirror-2026-09-11]
---

在此 mirror 仓库执行 push 前必须先 `git remote -v` 确认目标。本轮首次 push 误用 `git push origin ...` 打到 legacy 仓库；该次因 HTTP2 RPC 错误失败且未创建任何 ref（ls-remote 验证为空，无副作用），随后改 `git push lfl <branch>` 快进成功。另注：push+ls-remote 混在一条命令里时输出交错（出现过 "Everything up-to-date" 与 fatal 错误混排），回执歧义时分开单跑重验；`${PIPESTATUS[0]}` 才是管道首命令退出码。