---
title: GitHub push 执行规程 v2：remote 指向 / 分叉 / 凭据 / force / 验证五关（含自拷问修订）
scenario: llm-first-loop 多 remote（lfl=真实远端 / origin=legacy 冻结 / mainrepo=本地路径）、多 worktree、共享 checkout、headless 无 TTY 环境下，向 GitHub lfl 推送分支的完整流程；历史事故：推错 legacy 仓库、长会话不 fetch 分叉发现过晚、设备码授权阻塞、gh run watch 假阳性。
root_cause: ""
solution: 按 v2 规程执行：定位（lfl-only、禁裸 push/pull、HEAD refspec）→ 同步（双向计数、分支类型决定 rebase/merge、共享 checkout 红线）→ 凭据（401/403 分流、gh 与 git 凭据链不同步、设备码+分段等待）→ 推送（force-with-lease+覆盖清单审查）→ 验证（ls-remote SHA 一致、按 commit SHA 关联 CI run、推送与 CI 分层汇报）。
evidence: EXPERIENCE-20260917-llm-first-loop-mirror-origin-legacy-lfl; EXPERIENCE-20260919-llm-first-loop-mirror-origin-legacy-lfl-remote; EXPERIENCE-20260917-fetch-push; EXPERIENCE-20260909-github; EXPERIENCE-20260911-github-token-read-org-gh-auth-login-git-push; EXPERIENCE-20260919-checkout-main-git-branch-show-current-main-worktre; EXPERIENCE-20260912-gh-run-watch-WATCH-EXIT-0-ci; EXPERIENCE-20260820-git-users; EXPERIENCE-20260919-checkout-git-reset-hard-artifacts-owner-path; 本会话 git remote -v 实测（lfl/origin/mainrepo 三 remote）
tags: []
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-09-19T19:39:00.020639+08:00"
updated_at: "2026-09-19T19:39:00.020639+08:00"
supersedes: [EXPERIENCE-20260919-llm-first-loop-mirror-origin-legacy-lfl-remote, EXPERIENCE-20260909-github]
---

GitHub push 执行规程 v2（教训汇编+自拷问修订；grill_me 两次返回空问题模板，盘问为按焦点域自驱完成，下次可再试工具化拷问）。

【推送前定位】
- git remote -v：目标必须是 lfl（deyi2026/llm-first-loop）。origin=legacy（9/9 后冻结）禁推；mainrepo=本地镜像路径，仅在明确本地同步时用；gh 需显式 -R deyi2026/llm-first-loop。
- 禁止裸 git push / git pull / git fetch（无 remote 参数）：push.default 与 upstream tracking 可能指向 legacy；核对 git branch -vv。
- git branch --show-current 确认分支（主 checkout 可能停在任务分支，main 可能被 .worktrees/* 占用）；推当前分支用 git push lfl HEAD:refs/heads/<branch>。
- git status 自查：内容含 /Users/*/ 绝对路径会被安全扫描拦截。

【推送前同步】
- git fetch lfl --prune；双向计数 git rev-list --left-right --count HEAD...lfl/<branch>（单向 log 缺本地领先侧信息，影响决策）。
- 处置规则：推 main→只 fast-forward 或本地 merge 后推，永不 rebase/force；自有 feature 分支从未推送→可 rebase 到远端最新；已推送过（他人可能已基于）→加提交或 merge，不 rebase+force。
- 共享 checkout：fetch 只读安全；pull/reset --hard/switch 只在自己 worktree 内做。

【凭据】
- 先分 401（token 过期/无效→重新授权）vs 403（scope/权限不足/分支保护→查权限）。
- gh auth status 绿灯≠push 凭据可用：git 走 credential.helper/keychain/env/askpass，与 gh keyring 不同步；临时桥接的凭据文件用后删除。
- 无 TTY 报 "could not read Username"：设备码 OAuth，输出 user_code+verification URL 给真人异地授权；等待用 schedule(wake)，wake 被拒则分段阻塞轮询（每段≤60s 工具超时）。
- 设备码 token 仅 repo scope：gh auth login 失败（缺 read:org）但 git push 可用，勿误判放弃。

【推送】
- git push lfl HEAD:refs/heads/<branch>；默认禁 force。确需 force 且用户明确授权时：①执行前最后一次 fetch；②列出将被覆盖的远端提交；③清单含非本会话/非本人提交→拒绝；④用 --force-with-lease 不用 --force（挡 fetch 后远端又被推进的竞态窗口）。

【推送后验证】
- git ls-remote lfl <branch>：SHA==本地 HEAD 才算推送完成（退出码 0≠完成）。
- CI 按 commit SHA 关联 run（gh run list --commit <sha>），不按时间取最新（可能是别的分支）；conclusion=null→分段轮询到 completed（60s 超时约束，用后台 job 或 schedule）；不看 gh run watch exit code（假阳性）。
- 汇报分层："推送完成（SHA 一致）"与"CI 绿"分开陈述。

【失败分支】
- non-fast-forward→回同步节重新比对，绝不直接 force；401→重新授权；403→查 scope/权限/分支保护；网络超时→重试一次仍失败如实报告。