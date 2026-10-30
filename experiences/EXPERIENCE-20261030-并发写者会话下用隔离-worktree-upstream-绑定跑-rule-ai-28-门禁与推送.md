---
title: 并发写者会话下用隔离 worktree + upstream 绑定跑 RULE-AI-28 门禁与推送
scenario: "同一仓库有并发写者会话在途改动（我的交付期间对方提交了 P1-b 特性并继续改 src/llm_loop/tools/review_host_admission.py 与其测试）。我要对自己那部分交付跑 RULE-AI-28 的 review_admission(kind=full_test, command=\"bash scripts/ci_gate.sh\")：在主仓跑会把对方未提交的 WIP 一并冻结（include_worktree=True），门禁结果被污染；改用隔离 worktree 又被拒：full_test_no_delta（committed delta、worktree、untracked 全空）。"
root_cause: Host 的 review_admission 对 full_test 会把工作树 diff 一并冻结（并发写者会话的在途改动污染被审产物）；而 detached worktree 没有 upstream/push 目的地，导致审查 delta 计算为空而被 full_test_no_delta 拒绝。
solution: "1) 建隔离 worktree：git worktree add --detach <repo内data目录> <commit>（放 data/ 下，已被 .gitignore 忽略，不污染 git status；scripts/ci_gate.sh 原生支持 worktree，会回退主 worktree 的 .venv 并 symlink node_modules）；2) worktree 里必须建分支并绑定 upstream，否则 Host 锚定不到推送目的地、delta 为空被拒：git -C <wt> checkout -b <branch> <commit> && git -C <wt> branch --set-upstream-to=origin/main <branch>；3) 之后 review_admission(kind=full_test, workdir=<wt>) 的 delta = 远端 tip..HEAD，canonical 门禁在干净树上跑；4) 推送门禁同样在隔离 worktree 里做：review_admission(kind=git_push, command=\"git push origin <branch>:main\")，审查的 delta 与实际推送内容一致；5) 执行 push 前必须先调用 review_admission(action=status, child_id=...) 让 Host 在内存里签发一次性资格，否则命令被 RULE-AI-28 闸拦（只做 subagent_result 不算数）；6) 推送用目标提交 refspec，既能只推自己的提交又保持分支拓扑（不制造分叉）。"
evidence: "evidence://v1/024e928cf34d87e6d363d02fca382479b0e13b4aa5afb42acac710db5545efa2（隔离 worktree 上 full_test 准入候选 74a32513… PASS）；evidence://v1/5f1443ce35a86a77a3bab8d85e59f25fbd4f69e3df02fc2dd2dc27212057bc33（git_push 准入候选 7365b634… PASS）；evidence://v1/9d3b7f02920ba4d0758bf9ab07e817e8613b0e4c126c5dd242af0d5a98c7ba18（推送结果 origin/main=594db8ddb）"
tags: [rule-ai-28, 并发写者, review_admission, worktree, git_push, 交付]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T16:06:29.106629+08:00"
updated_at: "2026-10-30T16:06:29.106629+08:00"
supersedes: [EXPERIENCE-20261030-rule-ai-28-push-闸漂移-本地标记提交-按-sha-推送-material-锁定为提交, EXPERIENCE-20261028-沙箱只读目标仓时-git-push-走可写-worktree-裸命令-git-push-remote, EXPERIENCE-20261030-并发会话在途改同一文件时的推送提交构造纪律]
---