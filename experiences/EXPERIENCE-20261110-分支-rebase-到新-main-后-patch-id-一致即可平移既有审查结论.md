---
title: 分支 rebase 到新 main 后，patch-id 一致即可平移既有审查结论
scenario: 把一个长期未合的分支 rebase 到已前进多个提交的 main 时，既有独立审查 PASS 覆盖的是 rebase 前的提交；直觉上要重跑整轮合并审查。实际风险只在于 rebase 是否改写了补丁内容（冲突解错、上下文漂移引入意外改动），与 base 前进了多少无关。
root_cause: ""
solution: "用 patch-id 做机械判据，而不是重跑整轮审查：1) rebase 后立即对比 `git diff <old_base>..<old_head> | git patch-id --stable` 与 `git diff <new_base>..<new_head> | git patch-id --stable`；2) 同时核 diff --stat 文件数与增删行数；3) 两者一致即证明补丁内容等价，旧审查结论可平移，只需在 rebase 后的树上复跑 focused gate（本次 300 passed）作为环境回归；4) 若 patch-id 不一致，说明 rebase 改写了内容，必须重审。审查回执里记 rebased_from{old_commit, old_base, patch_id, patch_identity} 让\"结论可平移\"这句话可核验，而不是只有主张。"
evidence: 2026-11-10 实测：分支 fix/review-findings-none-placeholder-20261109 原提交 cd6bdec65（base 75ed7eb3a）→ git rebase main（e64d67b92）→ b98c9a446。`git diff 75ed7eb3a..cd6bdec65 | git patch-id --stable` 与 `git diff e64d67b92..b98c9a446 | git patch-id --stable` 输出同一 patch-id 273d4d7e5b3bcbd6a00ca7a405bb3293d65a0884，两段 diff 均 2 文件 +70。合并审查子代理在 rebase 后用同一清单复核（含自跑 300 passed in 35.46s）仍给 PASS，ff 合并 main=b98c9a446，树与分支零差异；随后 ci_gate 全链路 exit=0、push 闸 PASS，origin/main=b40115bc8。
tags: [git, rebase, review, patch-id, RULE-AI-34]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-10T22:58:37.963151+08:00"
updated_at: "2026-11-10T22:58:37.963151+08:00"
---