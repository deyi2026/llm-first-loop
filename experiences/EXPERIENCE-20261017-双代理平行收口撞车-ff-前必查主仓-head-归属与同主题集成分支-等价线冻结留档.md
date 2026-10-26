---
title: 双代理平行收口撞车：ff 前必查主仓 HEAD 归属与同主题集成分支，等价线冻结留档
scenario: 多会话共享仓库的分支收口工程：已按族 cherry-pick 集成、走完 R28 三轮审查与 RULE-AI-34 merge-gate PASS，准备 ff 合入 main。
root_cause: ""
solution: 在 ff 收口动作前增加强制检查：主仓 HEAD checkout 归属 + 最近 10 分钟分支活动 + 同主题 integrate/final 分支存在性；发现平行实现时按覆盖面裁定承担方，等价线冻结留档防重复合并。
evidence: "evidence://v1/91502497ba3220f4252c91244cee9b263615faea356e9f4c603de36897493853（merge-gate spawn）；evidence://v1/81a3912c46dbe0483cd6c9649e43a8c34d178228ef3dfbf23610c2be6427a564（02:15 ff 可行性检查，未含主仓 HEAD）；evidence://v1/44d31703d2b4e20ccbb9be2873bfa5466a15b388d52699（主仓 HEAD 在 final 的发现）；evidence://v1/1508233252b36771be2873bfa5466a15b388d52699 差异定性回执"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T02:29:23.846984+08:00"
updated_at: "2026-10-17T02:29:23.846984+08:00"
---

同一共享仓库多会话并行推进同主题收口（F 批未合并分支处置）时，两个代理各自完成了完整的"集成分支→cherry-pick→独立审查→merge-gate PASS"链，直到一方准备 ff main 时才发现主仓 HEAD 已被另一方 checkout 到等价集成分支（integrate/f-batch-final-20261017），双方产出为语义等价的平行实现（同主题修复各自实现一遍，REVISE 修复、durability 登记均重复完成）。教训：收口 ff 前必须先查主仓 HEAD 归属（git branch --show-current）与最近分支活动（for-each-ref --sort=-committerdate），本集在 02:15 只查了"main 是否祖先/ff 可行"漏查了 checkout 归属，多花了一轮 merge-gate。处置原则（已验证有效）：覆盖面更广的线（final 含 f-batch 旧线+全量 9228 回执）承担合入；等价线冻结 ff、以分支+evidence tag 保全独立验证链并在回执 commit message 记录裁定；内容包含性用 git diff <final> <mine> -- src/ tests/ 的 + 行逐条定性（全部为等价修复的平行实现⇒安全冻结）。