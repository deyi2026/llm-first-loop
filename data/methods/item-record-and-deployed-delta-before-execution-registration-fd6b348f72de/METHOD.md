---
method_id: item-record-and-deployed-delta-before-execution-registration-fd6b348f72de
name: item-record-and-deployed-delta-before-execution-registration
description: 对一条先前批准的变更单（EVO/ticket/审批项）执行或登记完成前，先读单据原文并与当前部署 delta（运行 manifest 的 git_head、review 时 head..当前 head 的 commit、运行代码本身）比对：若提案已随某 commit 上线（live 代码常自引用单据 ID），本次'执行'退化为状态闭环，登记 note 须如实写明已落地 commit 与闭环性质，不得虚构'审批后执行'叙事；仅当 delta 中无实现时才走真实实施。本集单据原文留到第 12 轮才读，而第 3 轮运行代码注释已引用该 EVO ID、第 9 轮 git log 已含实现 commit——把单据+delta 比对前置可提早约 8 轮发现'执行已退化'这一改变答复口径的关键事实。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1186:dbc9777a331f3c5abd9e
evidence_refs: learning:learn:42814f97ccfe
created_at: 2026-10-18T01:23:24.860974+08:00
updated_at: 2026-10-18T01:23:24.860974+08:00
---
## Trigger
需要执行或登记完成一条先前批准的变更单/审批项（EVO、ticket、审批流），且运行环境存在审批与部署不同步（服务重启、滚动发布、多服务 git_head 不一致）

## Discriminator
三个当时即可观察的事实任一成立即可缩小搜索：(1) 运行中代码的注释/分支自引用该待办项 ID（提案已实现的最强信号）；(2) git log(审批时head..当前运行head) 中存在语义匹配提案的 commit；(3) 单据 reviewed_at 早于当前进程 started_at，说明审批发生在旧代码上、解释状态滞留

## Short path
- 按 ID 从权威台账（如 evolution_suggestions ledger）读单据原文，取 content/status/reviewed_at——未知量：要执行的具体是什么、是否仍 pending
- 读受影响服务的 runtime manifest 取 git_head 与 started_at，对比 reviewed_at——未知量：审批是否发生在旧进程、当前代码是否含该变更
- 在运行代码中定位提案对应函数/分支，并 git log 旧head..新head 查是否存在实现该提案的 commit——未知量：变更是否已实现并上线
- 若已实现：执行退化为状态闭环，登记 note 如实写'已随 commit X 落地、本次为补状态闭环'；若未实现：转入真实实施路径
- 最后核对登记工具契约（必填字段、executor 取值 Literal）后登记，读回执确认状态推进，停止

## Stop conditions
- 单据内容已与某个已部署 commit 一一对应，且登记回执确认状态推进成功
- 确认 delta 中无任何实现该提案的 commit，转入真实实施分支后停止本方法

## Verification
- grep 权威台账确认单据当前 status 与 reviewed_at 未被并发修改
- 确认运行 manifest 的 git_head 包含实现 commit（git log 或 merge-base --is-ancestor）
- 登记回执 registered=true 且 note 中不存在任何未实际发生的执行动作描述

## Counterexamples
- 提案在 delta 中无对应 commit 且运行代码无该分支 → 必须真实实施，不得以'闭环'话术登记
- 待办项是无代码制品的过程性指令（如调整策略、改文档流程）→ 无从与 git delta 比对，直接执行并如实汇报
- 审批与执行原子同版、无重启/发布滞后的冻结系统 → reviewed_at vs started_at 与 head 差异无信息量，跳过比对
