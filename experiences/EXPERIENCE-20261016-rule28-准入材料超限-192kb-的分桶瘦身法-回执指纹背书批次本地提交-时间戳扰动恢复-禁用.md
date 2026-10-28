---
title: Rule28 准入材料超限的分桶瘦身法（历史上限 192KB，现行 2.5M 字符）：回执指纹背书批次本地提交 + 时间戳扰动恢复，禁用 stash 缩材料
scenario: 【历史现场，2026-10-16 当时上限 192KB；现行上限为 2.5M 字符，239KB/407KB 都已远在限内，不再触发】review_admission(kind=full_test) 启动被拒：review_artifact_exceeds_192kb（未提交 delta 239KB）或 git_state_too_large（隔夜并行 Goal 留下 staged 批次+reports 时间戳扰动 407KB）；当时需在不绕过审查、不污染审查对象的前提下把 git 状态压回限内
root_cause: ""
solution: 先按目录分桶量化 diff 体积定位大头；有 PASS 回执（指纹逐字节核对一致）的批次做本地提交收敛 delta；纯时间戳再生成类 reports 扰动 git checkout 恢复；保持树零改动重试 admission。禁用 stash 缩材料（中断后留半成品，恢复需指纹核对）
evidence: "review_admission 拒绝回执（review_artifact_exceeds_192kb 2026-10-15T23:10 / git_state_too_large 2026-10-16T09:22）；commit c72a615c0（batchB 按指纹落地，准入材料 239KB→70KB 后 r2 PASS）；git checkout -- reports/（407KB→84KB 后 r6 PASS candidate=caca079e）；全量门 exit=0（job-9185f79efba749548441，09:34）"
tags: [rule28, review_admission, git, admission-artifact-size, 跨会话恢复]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T09:36:34.045722+08:00"
updated_at: "2026-10-16T09:36:34.045722+08:00"
---
> **当前适用性（2026-10-28 复核）**：Rule 28 审查材料上限已由 192KB 提高到 **2.5M 字符**（超限码 `review_artifact_exceeds_cap`，见 docs/ai_rules.md / EVO-20261023-fc5c34b9）。本卡里的 192KB 是当时事故现场，不是当前门禁：材料未接近 2.5M 时**不需要**任何分桶瘦身。仍可迁移的只有三条机制结论——材料=未提交的全部 git 状态（staged+unstaged+untracked）、只有带逐字节指纹 PASS 背书的批次才能本地提交收敛、缩材料禁用 stash。

背景：Rule28 review_admission 会把未提交 git 状态（staged+unstaged+untracked）整体冻结为审查材料；2026-10-16 当时上限为 192KB（实测两种拒绝面：review_artifact_exceeds_192kb / git_state_too_large），当前为 2.5M 字符。

处置三步（2026-10-15/16 GOAL-20261015-ac085ab1 实测有效）：
1. 分桶量化（git diff HEAD -- src tests / docs / reports 分别 wc -c）：本例 407KB 中 reports/ 占 323KB——18 个 *.json 全部是测试运行再生成的纯时间戳扰动（141+/141-，仅 started_at/wall 变化）。
2. 合规瘦身：a) 有独立 PASS 回执（含逐文件 sha256 指纹）背书的批次 → 本地提交（非 push，不触碰 push/发表门），把未提交 delta 收敛到“仅待窄审的新修复”；b) 纯时间戳类 reports 扰动 → git checkout -- reports/ 恢复（下轮全量测试自动再生成，零语义损失）。提交前必须 shasum 与回执指纹逐字节核对，防审查后漂移。
3. 重试准入：树零改动下 start（candidate_sha256 应可复现）→ 轮询 status → PASS 后立即执行被门控命令。

反例与边界：不要用 git stash 缩材料——上游曾用 stash 收走 batch B，会话中断后留下“文件失踪”半成品（.pyc 残留误导），恢复成本高且工作树与准入材料错位；守护测试可能按 staged 口径读源（local_imports ratchet 实测），修复必须 git add 后守卫才可见。