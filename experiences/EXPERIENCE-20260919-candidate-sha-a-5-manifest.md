---
title: Candidate SHA 冻结：合并远端、清偿门禁债、单 A.5 manifest，再推送
scenario: 长生命周期本地演化分支（84+ commits 未推送、远端 main 已前进）需要收敛冻结，且冻结本身要过 CI 门禁与 A.5 申报
root_cause: ""
solution: 冻结优先于新功能：合并远端→清偿门禁债→单 manifest 全范围申报→本地全量门禁→推送开 PR。僵尸 git 状态先核暂存区再处置。
evidence: "PR #34 (freeze: converge exec-surface followup line into main)；commit 757bbbfa7 fix(ci) 门禁清偿；manifest docs/governance/submissions/20260919-exec-surface-followup-convergence.json"
tags: [git, ci-gate, a5-manifest, freeze]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-19T12:18:39.280875+08:00"
updated_at: "2026-09-19T12:18:39.280875+08:00"
---

背景：gen40 线在合并前累积 84+ commit 领先，门禁债（ruff 14 错/pyright 2 错）与 A.5 manifest 缺失沉底。做法：(1) 僵尸 CHERRY_PICK_HEAD 指向 HEAD 自身、暂存区为空 → abort 而非 continue；(2) merge 远端 main（同名测试双侧独立 rename 冲突保留较新侧）；(3) 合并树上清偿全部门禁债后才 push；(4) 单份 A.5 manifest 分区 367 路径；(5) 本地 CI 同款门禁先行。教训：未推送提交的 CI 从未运行，门禁债按提交数复利；冻结后每个 PR 保持必绿，未再沉底。