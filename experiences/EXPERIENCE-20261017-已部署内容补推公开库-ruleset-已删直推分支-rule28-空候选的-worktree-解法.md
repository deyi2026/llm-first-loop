---
title: 已部署内容补推公开库：ruleset 已删直推分支 + Rule28 空候选的 worktree 解法 + merge 窗口祖先断言
scenario: 公开库（deyi2026/llm-first-loop）同步：已部署内容补推 + Rule28 git_push 准入空候选 + ruleset 已删除的事实核查
root_cause: ""
solution: "推送前实时 GET rulesets 与 branch protection（不复用旧结论）；准入走\"净化镜像 worktree + 字面 push 命令\"；merge 窗口用祖先断言替代线性父断言"
evidence: "ls-remote 终验 lfl/main=b9bf967d8c86652e9c4f417375c1c6a330196918（2026-10-17 13:55）；admission PASS candidate b407a3458b641d80ea4cd64636e84f8f85dba7ae9b0dbfb325c3160cad51b922（subagent_8bfc11315c96）；push 回执 b68dbc2a5..b9bf967d8 main->main；rulesets 空列表 + branch protection 404；feishu pid 25059 13:37:16 / learning svc-42346a6112 succeeded（gen 275 全对齐）"
tags: [public-sync, rule28-admission, git-push, ruleset, deployed-state, sanitize-replay]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-17T13:58:56.266748+08:00"
updated_at: "2026-10-17T13:58:56.266748+08:00"
---

场景：已部署状态（desired generation 的 git_head）需要补推公开库 lfl/main，但远端落后 34 提交、工作区又叠加并行会话的未提交 WIP 与新增提交。三个新事实与解法：
(1) ruleset 23421644 已删除：gh api rulesets 列表为空、branches/main/protection 返回 404 "Branch not protected" → 直推畅通，sanitize-sync 脚本第一分支（合规直推）适用，暂停窗口协议本轮不需要。推演时必须实时 GET rulesets 确认，不能沿用 8 天前"直推必拦"结论。
(2) Rule28 git_push 准入对"已部署内容补推"的空候选问题：准入冻结以工作区 git 状态为准，干净树+HEAD==deployed 时 committed_delta 为空 → 独立审查者正确拒绝（REVISE: empty candidate）。脚本包装命令又被 kind 契约拒绝（review_kind_command_mismatch）；裸仓库 workdir 冻结失败（git_state_unavailable）。已验证解法：从净化镜像克隆挂非裸 worktree（checkout 待推 tip、远程跟踪存在 → committed_delta=真实待推提交），admission 用 workdir=worktree + 字面 `git push github refs/heads/main:refs/heads/main`（与脚本 push_main 逐字一致），独立审查者看到真实 delta 后正常 PASS。
(3) sanitize-sync 脚本第 4 步的父==远端main 断言假设线性增量；窗口含 merge commit 时断言必失败（ABORT 误报）。正确判据用祖先关系：merge-base --is-ancestor <远端main> <tip> && tip 树==本地树 && token 扫描零残留。本轮 34 提交无一触及 19 剔除路径 → filter-repo 恒等重放（净化 tip == 工作区 tip b9bf967d8），哈希不变本身就是确定性重放的最强证明。
操作顺序（可复用）：ls-remote 定远端 → 剔除路径/敏感词预检（git diff --name-only + git grep 预测）→ 镜像对齐远端 main → update-ref 待推 tip → rm filter-repo/already_ran → filter-repo 剔除集重放 → 祖先+树+token 三断言 → worktree 挂出 → admission(workdir=worktree, 字面 push 命令) → PASS 后单命令直发 → ls-remote 终验 → worktree remove。
另：工作区有并行会话在推进 main 时，stash WIP 要尽快还原（镜像流程不需要工作区干净）；第一轮准入审查落在 WIP 上的 REVISE 发现（P1/P2）要转交 WIP 归属会话处置，勿丢弃。