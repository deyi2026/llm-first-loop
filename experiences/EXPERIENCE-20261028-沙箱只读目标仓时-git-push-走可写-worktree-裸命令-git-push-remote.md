---
title: 沙箱只读目标仓时，git push 走可写 worktree + 裸命令 git push <remote> <branch>
scenario: 要把一个分支/提交推到 GitHub，但目标仓（如 llm-first-loop-mirror）的 .git 对我的沙箱只读（git fetch 写 .git/FETCH_HEAD 报 Operation not permitted，touch 仓库根也被拒），而开发 worktree 位于可写工作区内。
root_cause: ""
solution: 1) 不在只读仓里 fetch/merge：改在可写 worktree（/Users/<user>/lfl-workspace/.worktrees/lfl-dgui）里操作；该仓 git-dir 可写，git worktree add 出的临时干净 worktree（/Users/<user>/lfl-workspace/tmp-push-dgui）可作为推送执行目录，闸门看到的 porcelain 为 0 行。2) Host ReviewAdmission(kind=git_push) 只受理裸命令 git push <remote> <branch>：命令必须单段（无 &&、无管道、无 --dry-run、无 --force），remote 与 branch 两段齐全（冒号 refspec 会被拒 push_explicit_remote_and_ref_required）；workdir 必须是真正执行目录。3) 闸门产物 = ls-remote 得到的远端 base..推送源 commit 的 diff + 该目录未提交改动 + 未跟踪文件（上限 2.5M）；本次 283KB 通过。4) 推送后验证必须用 ls-remote/gh api 看远端真实 SHA；本地 refs/remotes/<remote>/<branch> 可能因沙箱拒写而更新失败，那只是本地跟踪引用陈旧，不代表推送失败。5) 回执目录若在只读仓，写到工作区（/Users/<user>/lfl-workspace/receipts/）并告知用户复制。
evidence: "git push lfl main（workdir=/Users/<user>/lfl-workspace/tmp-push-dgui）→ \"f00734d44..f5fec37c1  main -> main\"，exit 0；git ls-remote lfl refs/heads/main 与 gh api repos/deyi2026/llm-first-loop/commits/main 均为 f5fec37c1ca985ac69006a5203d579c7c8230071；Host admission candidate_sha256=690f84ac… qualification=PASS；独立子代理 PASS P0=0/P1=0"
tags: [git_push, review_admission, RULE-AI-28, sandbox, worktree, github]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T15:25:27.537523+08:00"
updated_at: "2026-10-28T15:25:27.537523+08:00"
---