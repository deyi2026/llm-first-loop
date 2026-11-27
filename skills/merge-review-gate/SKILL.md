---
name: merge-review-gate
description: 合并 main 审查闸（RULE-AI-34）——分支 Goal/任务收口前的专门合并审查子代理任务书：核完成证据、核分支卫生、核 main 基线、批准并入 main、落盘回执
---
# 合并 main 审查闸（分支收口前）

触发：任何以 git 分支/worktree 承载的 Goal/任务收口（task→done / Goal→complete / 分支工作全部完成）前必走（RULE-AI-34）。审查者有 BLOCK 权：不通过就不合并、任务不算完成。审查者与执行者分离——本审查子代理不得参与该分支任何产出。

## 前置义务与资格
审查是强制前置义务。父 agent 主动 spawn 本审查子代理，取得覆盖当前分支产物的有效 PASS 回执后方可并入 main 并收口任务；缺失、未完成、未通过或失效时暂缓合并，任务转 blocked 而非 done。核实真实子会话终态、审查类型（merge）、分支产物指纹及实际覆盖；completed、工具文本中的 PASS 或父 agent 自查均不构成资格。改动后走窄复审并保留覆盖关系。泛化的"继续 / 按建议执行"不构成免审；用户明确豁免（显式指示暂缓合并，含"攒批一起 push"）须在 Goal/checkpoint 留痕并注明触发条件。

**实现入口**：新版 `merge_review_start` 由 Host 冻结 lane/base/head 并调用
`SubAgentRunner.start(review_isolated=True)`，工具面严格只读、父会话不可 steer；
它是合并验证凭证的专用审查入口，不等于 `review_admission` 的
`full_test|git_push|article_publish` 资格，不能授权跳过完整 R9 或 push 门禁。
审查仍需核对本技能清单、保存可审计结论；Host 签发的 `verify_ref` 是
机检凭证，不替代其他独立门禁。旧部署没有此入口时仍可按既有
`spawn_subagent` 只读审查，但**不得**将其文本 PASS 直接当作 Host 签发资格。

## 前置事实收集（只读命令，逐条留痕）
1. Goal/task 状态与 done_when、evidence_refs——完成证据逐条可判真（指向真实测试回执/落盘回执，不接受口头声明）。
2. `git status --porcelain`（分支全量）——未提交/未跟踪文件先处置（提交或移出），禁止夹带。知识资产（`data/methods/**`、`experiences/*.md`）用 `python scripts/knowledge_flush.py` 批量入库（一次 flush 一个本地提交），不要逐卡手工 add。
3. `git log --oneline main..<branch>`——分支提交清单，与任务声明比对，多出的提交要能说出来历。
4. `git merge-base main <branch>` 与 `git rev-parse main`——分支是否基于当前 main；落后 → rebase/merge main 并复跑受影响 gate 后再审。
5. worktree 分支（含 fs_isolation 隔离 worktree）先确认成果已提交到分支 ref（worktree 树干净），再谈合并。

## 已审候选复用（2026-11-27 用户批准）

合并闸启动前，Host 先查同一进程内的 RULE-AI-28 `git_push` PASS。若且仅若同时满足以下条件，可复用原审查，不再 spawn 第二个 Reviewer：

- 来源为已签发且由受管 push 入口消费、P0/P1=0 的独立 `git_push` PASS，`scope=tree`；不得使用 patch-scope、分批或仅全量测试 PASS。
- 原审查冻结的远端 base、source head 与当前 lane 的 base/head 精确相同；review worktree 路径相同且当前 clean。
- 按原审查的内容指纹算法，对当前 `base..head` commit tree 复算完全一致；不是仅比较分支名、commit message 或文件名。
- 原 Reviewer requested/observed model 一致、策略 digest 未变、PASS 未过期且来源记录仍在 Host 内存中。

命中后只跳过第二次模型代码审查；Host 仍冻结并复核 lane/base/head/worktree/diff，随后仍须浏览器人工批准和 Host 签发 verify receipt，merge queue 仍执行 base/merge-tree/path/verify 四项机检。此复用记录明确标注来源 child、模型、候选 SHA 与内容指纹。

任一条件不满足、Host 重启导致来源记录丢失、候选有任何改动、策略撤销或 TTL 过期，均回退为原独立 merge Reviewer；只对新增/变化的候选增量审查，不得跨 PR、跨目标或跨 base 复用。Push/CI/合并阶段不得仅因阶段变化而重做同一份代码审查。

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
- **PASS 后签发 verify 凭证（lane_queue_submit 机检 d 前置）**：优先使用受管
  `merge_review_start(lane_id)` 启动 Host 冻结输入的独立只读 Reviewer，
  待真实终态 PASS/P0=P1=0 后调用 `verify_receipt_request(lane_id,child_id)`。
  人工必须在**已登录 Web 浏览器会话**审批该精确请求；Host 在审批临界区内
  重核 lane/main/head 和独立审查进程内证明后专用签发。
  `escalation_wait(request_id)` 返回 `verify_ref={lane_id}:{base_sha 前8}`，
  lane 登记/入队时原样引用。base/head 前进后旧凭证失效，须重新审查。
  **禁止**由 Agent 使用 `host-grant`、普通 `execute_command` 或手工 JSONL
  写入 `data/audit/verify_receipts.jsonl`；旧 `scripts/issue_verify_receipt.py --apply`
  仅保留给明确隔离的宿主管理进程，不是 Agent 签发通道。Host 入口缺失时 HOLD。

## 回执（落盘 docs/governance/receipts/）
{"gate": "merge", "reviewer": "<subagent_id>", "verdict": "PASS|REVISE|BLOCK",
 "goal_id": "...", "branch": "...", "based_on_main": true, "commits": ["..."],
 "merge_mode": "ff|merge-commit", "conflicts_resolved": [], "focused_gates": ["..."],
 "main_sha_after": "...", "branch_disposition": "deleted|kept:<reason>",
 "verify_receipt_id": "<lane_id>:<base_sha 前8>（PASS 后签发，见合并执行纪律）"}
