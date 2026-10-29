---
name: merge-review-gate
description: 合并 main 审查闸（RULE-AI-34）——分支 Goal/任务收口前的专门合并审查子代理任务书：核完成证据、核分支卫生、核 main 基线、批准并入 main、落盘回执
---
# 合并 main 审查闸（分支收口前）

触发：任何以 git 分支/worktree 承载的 Goal/任务收口（task→done / Goal→complete / 分支工作全部完成）前必走（RULE-AI-34）。审查者有 BLOCK 权：不通过就不合并、任务不算完成。审查者与执行者分离——本审查子代理不得参与该分支任何产出。

## 前置义务与资格
审查是强制前置义务。父 agent 主动 spawn 本审查子代理，取得覆盖当前分支产物的有效 PASS 回执后方可并入 main 并收口任务；缺失、未完成、未通过或失效时暂缓合并，任务转 blocked 而非 done。核实真实子会话终态、审查类型（merge）、分支产物指纹及实际覆盖；completed、工具文本中的 PASS 或父 agent 自查均不构成资格。改动后走窄复审并保留覆盖关系。泛化的"继续 / 按建议执行"不构成免审；用户明确豁免（显式指示暂缓合并，含"攒批一起 push"）须在 Goal/checkpoint 留痕并注明触发条件。

**实现入口（本闸无 Host 冻结入口，勿照抄 RULE-AI-28 路径）**：RULE-AI-34 的程序角色为"无新增"，`review_admission` 的 kind 仅 `full_test|git_push|article_publish`，`classify_review_gate_command` 不识别 `git merge`。故本闸审查者由父 agent 直接 `spawn_subagent`（未参与该分支任何产出的只读子代理，任务书=本 skill），资格 = 清单逐条核验 + `docs/governance/receipts/` 落盘 merge 回执，没有进程内一次性资格可依赖。`spawn_subagent` 无 `review_isolated` 参数，不得据此声称取得 RULE-AI-28 那类 Host 资格；反之 RULE-AI-28 的资格也不替代本闸回执。

## 前置事实收集（只读命令，逐条留痕）
1. Goal/task 状态与 done_when、evidence_refs——完成证据逐条可判真（指向真实测试回执/落盘回执，不接受口头声明）。
2. `git status --porcelain`（分支全量）——未提交/未跟踪文件先处置（提交或移出），禁止夹带。
3. `git log --oneline main..<branch>`——分支提交清单，与任务声明比对，多出的提交要能说出来历。
4. `git merge-base main <branch>` 与 `git rev-parse main`——分支是否基于当前 main；落后 → rebase/merge main 并复跑受影响 gate 后再审。
5. worktree 分支（含 fs_isolation 隔离 worktree）先确认成果已提交到分支 ref（worktree 树干净），再谈合并。

## 审查清单
1. **完成证据**：done_when 逐条满足，evidence 真实。
2. **分支卫生**：树干净、提交原子、无夹带（同 push 闸第 2 条精神）。
3. **基线新鲜**：基于当前 main；落后已 rebase 并复跑受影响 focused gate。
4. **测试面**：任务相关 focused gate 通过；全量测试义务归 RULE-AI-28 代码闸（引用其回执，不重复跑）。
5. **合并方式**：可 fast-forward 则 ff；需 merge commit/冲突解决时，冲突解决点须在回执列出并窄复审。
6. **合并后**：main 受影响面冒烟 + 按分支卫生契约处置已合并分支（删除或标记保留理由）。

## 合并执行纪律（默认父会话按 PASS 回执执行，审查者不直接动 main）
- fast-forward：`git checkout main && git merge --ff-only <branch>`，核对合并后 `git rev-parse main` == 合并前分支 HEAD。
- 需 merge commit/冲突解决：解决点留痕，合并后跑受影响 focused gate。
- 合并后 `git log --oneline -3` 与回执 SHA 一致才算收口；Goal complete 的 evidence_refs 引用本闸回执。

## 回执（落盘 docs/governance/receipts/）
{"gate": "merge", "reviewer": "<subagent_id>", "verdict": "PASS|REVISE|BLOCK",
 "goal_id": "...", "branch": "...", "based_on_main": true, "commits": ["..."],
 "merge_mode": "ff|merge-commit", "conflicts_resolved": [], "focused_gates": ["..."],
 "main_sha_after": "...", "branch_disposition": "deleted|kept:<reason>"}
