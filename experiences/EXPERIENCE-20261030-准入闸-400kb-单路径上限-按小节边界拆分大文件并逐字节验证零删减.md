---
title: 准入闸 400KB 单路径上限：按小节边界拆分大文件并逐字节验证零删减
scenario: 要把含 677KB 单文件 manifest 的提交推上 origin，review_admission 连续返回 git_state_too_large，push 走不出去。
root_cause: 准入闸对单次 git 输出设 400KB 硬上限，而运行期输出投影在其之后执行，使 400KB–1MB 的 reports/** 文件处于「可提交但推不进」的死区。
solution: "先用 `git diff --binary base head -- <path> | wc -c` 逐路径量字节数定位越界者（本次只有 1 条 687,317B）；按该文件自身的内容小节边界（本次用 `### method:<id>` 标题 + 字节中点）拆成多份、每份低于 400KB，两侧各以完整小节收尾；拆完重建 concat 与原文逐字节 diff 验证零删减再入库。注意运行期输出投影（_project_committed_runtime_diff）应用在 _path_diffs 之后，而 400KB 上限在 _path_diffs 之内先抛错 ⇒ 投影救不了这份文件，只能拆。"
evidence: "review_admission 候选 077801fb 连续返回 git_state_too_large；拆分前单路径 diff 687,317B，拆分后两份 338,937B / 338,643B，rebuilt==original（676,921B，diff 为 0）；随后 git_push 第二、三轮审查 PASS 并推送成功（origin/main fc1c2d0d6 → 566e5b09f）"
tags: [review_admission, 准入闸, git, 拆分, 零删减校验]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T14:45:45.279660+08:00"
updated_at: "2026-10-30T14:45:45.279660+08:00"
---