---
title: 公开库 main 分支保护与 A.5 门禁的发布流程（v0.6.28 实测）
scenario: 向 deyi2026/llm-first-loop 公开库推送 main 时被分支保护拒绝（required status checks），或 CI 上 A.5/安全扫描/pyright 门禁失败需要定位
root_cause: ""
solution: 走 PR 门禁流程：功能分支 → PR → 等 CI 全绿 → merge；每个 PR 附一份覆盖全部变更路径（含 manifest 自身）的 docs/governance/submissions/*.json；树内不出现真实本机路径；CI pyright 报错用显式注解+isinstance 收窄修复
evidence: "PR #65（https://github.com/deyi2026/llm-first-loop/pull/65）与 PR #66 合并成功、Release v0.6.28 发布成功（https://github.com/deyi2026/llm-first-loop/releases/tag/v0.6.28）；A.5 manifest 两次修复（自覆盖、图重命名同步）；check_architecture_submission.py 本地 PASS 回执；git_security_scan 命中两次脱敏后 PASS。"
tags: [github, branch-protection, pr-gate, a5-manifest, release-flow]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T17:23:48.321782+08:00"
updated_at: "2026-10-10T17:23:48.321782+08:00"
---

deyi2026/llm-first-loop 公开库 main 有分支保护：直接 push 被拒（3 of 3 required status checks not succeeded）。正确路径：push 功能分支 → gh pr create → CI 门禁（A.5 架构提交审查 + 安全扫描 + pytest/ruff/pyright 三件套，全量约 8-11 分钟）→ gh pr merge --merge。三个坑：(1) A.5 要求 PR diff 里恰好一份 docs/governance/submissions/*.json manifest，且 manifest components 的 paths 必须与 base...head 三点 diff 的 changed paths 双向精确相等——包括 manifest 文件自身（用 git -c core.quotepath=off diff --name-only 取路径，避免非 ASCII 路径带引号入库）；(2) 安全扫描 --tree 拦本机绝对路径（/Users/<name>/、/home/<name>/），方法卡/文档示例必须写 <占位符>；(3) CI 的 pyright 严格模式会报本地 pyright 不报的推断错误（Unknown 传染），修复用显式类型注解 + isinstance 收窄。版本发布额外步骤：版本面四文件（pyproject/web routes.py SERVICE_VERSION/README 中英）+ CHANGELOG + uv.lock 一起提交，打 annotated tag，Release workflow 生成草稿后 gh release edit --draft=false --latest 发布。