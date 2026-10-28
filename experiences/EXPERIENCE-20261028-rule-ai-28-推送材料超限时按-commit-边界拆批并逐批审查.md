---
title: RULE-AI-28 推送材料超限时按 commit 边界拆批并逐批审查
scenario: "需要把大量累积提交（含数百个知识卡文件）推到远端，但 RULE-AI-28 的 git_push 独立审查有材料体积上限（cap 2,500,000B）；一次性整体推送被拒，材料 2.7MB。"
root_cause: ""
solution: "按 commit 边界拆批，每批一次独立 review_admission + 一次 push（refspec 写成 `<sha>:main` 显式限定范围），批间用 `git ls-remote` 确认远端已到上一批 SHA。拆批依据先量补丁体积：`git diff <remote_sha> <mid_sha> | wc -c`；把纯代码/文档批与大数据批分开，通常一批几百 KB、一批 2MB 左右各能过。每批 admission 的 push_remote_commit 会自动反映上一批结果，说明边界正确；最终以 `git ls-remote` + `rev-list --left-right --count <remote>/main...main = 0 0` 验收，而不是以审查 PASS 代替推送结果。"
evidence: "1) review_admission(git_push) 首轮整体推送被 `review_artifact_exceeds_cap` 拒绝（material 2,715,039B > cap 2,500,000B）。2) 拆两批后：A `git push lfl dfb627bee:main` 审查 PASS 并推送成功（33844108c→dfb627bee）；B `git push lfl f00734d44:main` 审查 PASS 并推送成功（dfb627bee→f00734d44）。3) 远端核验：`git ls-remote lfl refs/heads/main` = f00734d44，`rev-list --left-right --count lfl/main...main` = 0 0。证据 refs: evidence://v1/82f53fb8c460cc750993de0433f9bc9533ea8d0c446445b39f321b310424987b（A 推送回执）、evidence://v1/98d9d4dec50bad2d1f46340ddbfbf8b3ae3c82461a8ad919ea431698250182d5（B 推送回执）、evidence://v1/ed52391a5e17d39ad4514b40127568688fb651ce5d7a5316c93044eead7a6d36（远端=本地=0 0 核验）"
tags: [rule-ai-28, git-push, review-gate, material-cap]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T09:34:40.913303+08:00"
updated_at: "2026-10-28T09:34:40.913303+08:00"
---