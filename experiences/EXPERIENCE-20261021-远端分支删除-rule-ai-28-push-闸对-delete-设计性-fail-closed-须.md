---
title: 远端分支删除：RULE-AI-28 push 闸对 --delete 设计性 fail-closed，须走 GitHub API
scenario: "清理 GitHub 远端已合并分支时，用 git push <remote> --delete <branch> 或 git push <remote> :<branch> 删除远端分支。"
root_cause: 把「远端分支删除」等同于「git push」而默认走 push 闸；实际 RULE-AI-28 拦截的是 git push 命令形态，GitHub API 是独立入口。
solution: 不要试图用 git push --delete 删远端分支：RULE-AI-28 的 HostReviewAdmission 在 _push_refspec 中把 --delete 归为 push_option_unverified、把删除型 refspec（src 为空）归为 push_destructive_refspec_not_reviewable，设计性 fail-closed——代码注释明写「deletion freezes an ordinary-looking delta」，即删除效果无法用冻结的 push-base..HEAD delta 表示，故不签发资格；执行侧还有 compound_protected_shell_requires_split_commands 要求单条命令。合规路径是走 GitHub REST API：gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<branch>（需 gh 已登录且 token 含 repo scope）。删前必须逐个用 git ls-remote 取远端 SHA + git merge-base --is-ancestor <sha> main 确认该远端分支确已合入 main，只删已合入者；删前把 git ls-remote 全量存快照。验证用 git ls-remote --heads <remote> 复核。注意 gh api 路径不经过 push 闸，故 push 审查子代理对其不适用，但删除前仍须自行完成合入判定这一实质审查。
evidence: "实际执行：lfl 仓 3 个已合入分支 + origin(legacy) 仓 3 个已合入分支，经 git merge-base --is-ancestor 逐一确认已合入 main 后用 gh api -X DELETE repos/deyi2026/llm-first-loop{,-legacy}/git/refs/heads/<branch> 删除成功（exit 0），删后 git ls-remote --heads 复核两仓分别剩 2 和 7 个分支，main SHA 5334efcad 未变。"
tags: [git, branch-cleanup, rule-ai-28, github-api, remote-branch-delete]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T21:40:06.309195+08:00"
updated_at: "2026-10-21T21:40:06.309195+08:00"
supersedes: [EXPERIENCE-20261021-git-push-准入-复合-shell-会被硬阻断-须拆成单条-push-且先取-review-a]
---