---
method_id: treat-cas-generation-conflict-as-authoritative-state-signal-8c64ee9ccd9e
name: treat-cas-generation-conflict-as-authoritative-state-signal
description: 当 CAS/publish 报 'expected=X current=Y' 类状态冲突时，不要重试或换参重跑；错误回执里的 current 值本身就是权威状态的定位符，应直接读取该状态记录，比较它与本次目标的身份字段，再决定 rebase/re-publish 或放弃。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:272:c220f276863d0deec2be
evidence_refs: learning:learn:e8ea1e9e633a
created_at: 2026-09-18T19:10:16.187031+00:00
updated_at: 2026-09-18T19:10:16.187031+00:00
---
## Trigger
compare_and_swap / publish / put-if-match 类操作抛出带 expected 与 current 值的世代或版本冲突错误，且 current 值可映射到一条可读的权威状态记录

## Discriminator
错误消息在抛出时已同时给出 expected=40 current=41——current 即权威记录的键；且该记录当时就在已知路径 data/runtime/managed_service_deployment.json，无需任何搜索

## Short path
- 解析冲突错误，取出 current 值，不重试原命令
- 读取权威状态记录（按 current 值定位），未知量：current 状态钉住的是什么身份
- 逐字段比较记录与本次目标（worktree 路径、git_head、artifact 哈希），未知量：目标是否已上线
- 用 git 合并基/祖先检查确认 lineage，未知量：两条线是否已包含彼此
- 若未包含：在 current 之上新建工作区做合并，从文件内容本身（冲突块三方对比）判定取边
- 用双方各自的测试验证合并语义，把合并引入的失败归因到具体一行交互后再修
- hand back 更新后的命令（generation 与路径同步更新），停止

## Stop conditions
- 记录逐字段比对 + lineage 检查已确认 current 状态是否含本次目标
- 合并 diff 恰等于目标变更集，无范围外内容
- 双方相关测试全部通过，或失败已归因到具体语义交互并修复

## Verification
- 合并后 diff vs current 基线必须精确等于目标变更集
- 双方各自测试套件（本线 + 对方线）均 exit=0
- 构建通过且工作区干净
- hand-back 命令中的 generation/路径与最新权威记录一致

## Counterexamples
- current 记录不可读或位置未知：此时才需要先做 discovery 定位权威存储
- 错误是 transient（timeout/lock 而非版本冲突）：正确动作可能是有限重试，本方法不适用
- 记录显示目标已完整上线：停止 rebase 流程，只做验证性 curl/健康检查
- 冲突块双方都有语义改动且无法从文件内容判定取边：需回到各自的测试/提交意图，不能按格式规则选
