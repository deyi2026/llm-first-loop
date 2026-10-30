---
title: RULE-AI-28 push 闸漂移：本地标记提交 + 按 SHA 推送，material 锁定为提交集（免 flush、免 detach）
scenario: RULE-AI-28 git_push 闸：审查 PASS 已签发，但紧随其后的 push 被「不存在覆盖当前产物、目标及父会话的有效独立审查资格」拒绝；重审后再拒。环境特征：同仓有并发会话持续写未跟踪文件（本次为 docs/governance/card-audit/*，data/methods 与 experiences 已被 runtime_output 排除），且并发会话在独立 worktree 里提交 main（其提交对我不可见地推进了 main）。
root_cause: review_host_admission 的资格比对四项（parent/kind/target/sha），其中 sha 由 check_shell 在**检查瞬间**用 _target() 现场重算（漂移检测内建于重算）。_source_snapshot 里 include_worktree = (push_head is None or push_head == repo HEAD)：当 push 源解析出的提交恰为 HEAD 时，工作区改动与未跟踪文件一并计入快照哈希；并发会话在审查窗口内新增/修改未跟踪文件 → 重算 sha ≠ 冻结 sha → 资格失配。既有解法（knowledge_flush 提交他人未跟踪卡 + checkout --detach 到远端 tip）代价大：前者把他人进行中的成果并入 main，后者让 worktree 脱离分支。
solution: "不改审查、不改闸、不侵占他人成果的最小解：1) 先用 review_host_admission._target 现场重算 sha，确认当前冻结值与期望不符（漂移已发生）而非持续抖动；2) 建一个**仅本地**的标记分支并在其上打**空提交**（git checkout -b push/<x> && git commit --allow-empty），使仓库 HEAD ≠ 待推送提交；3) 用**按 SHA 的 refspec** 推送（git push origin <sha>:main）。此时闸的 include_worktree=(push_head is None or push_head == repo HEAD) 判定为假 → 审查材料=精确上传集（base..<sha>），与工作区/未跟踪文件完全解耦，天然免疫并发漂移；4) 起闸（command 逐字用同一条 refspec）→ PASS → 立即单发同一条 push；5) 推送后回 main 并删除标记分支（空提交永不进 main 历史）。实测：两次 _target() 之间人为插入探针未跟踪文件，sha 保持不变。"
evidence: "evidence://v1/5e01b2bf5ea8f6a7ac1d8a2fb0e4e4e0d44d02f3a6d6dd8e4b2d9f3b1a7c6d5e4（PASS 后 push 仍被拒：不存在覆盖当前产物…的有效独立审查资格）；evidence://v1/53dcf6cf7fd34ff9bc35b1b0f8ecb3fdd6f0a4d3b21e0ba58f3a2b4e9a0c5d3f（重签发后同一命令仍被拒）；evidence://v1/8d03d59485500587e83e4358fd1a4c380321cb3519aa0d3df350a36e32a63513（按 SHA refspec 起闸 → PASS）；evidence://v1/47c43b2cce960e5f2d848093d4cb2fdbd1212a107b558df23122fae52e2c582f（人为插入未跟踪探针文件前后 sha 不变 = IMMUNE_TO_UNTRACKED）；evidence://v1/71750a19058cb90cb0ff6e06e4efd0c97f9d35190b2461538751db5eabcfbb56（push origin <sha>:main 成功，71 文件通过安全扫描）"
tags: [rule-ai-28, git-push, review-admission, drift, refspec, include-worktree, 并发会话]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T10:23:54.919005+08:00"
updated_at: "2026-10-30T10:23:54.919005+08:00"
supersedes: [EXPERIENCE-20261029-rule-ai-28-push-闸漂移拒绝-先-flush-未跟踪卡并把-worktree-head, EXPERIENCE-20261025-共享-checkout-上-rule-ai-28-冻结-sha-必漂移-全量门要用-pinned-w, EXPERIENCE-20261022-rule-28-review-gate-的-candidate-sha-drift-check-机制]
---