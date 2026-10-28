---
method_id: ledger-first-recovery-of-session-created-record-payloads-6a434adcecc9
name: ledger-first-recovery-of-session-created-record-payloads
description: 记录检索已按 ID 命中目标但正文截断、且该记录由本会话/本 workspace 内的第一方工具调用（如 submit_evolution）创建时，把会话 evidence ledger 当作第一查询对象：按记录 ID search_evidence 直接取原始工具回执；若回执载荷本身也被截断，再用事件元数据中的 session id 直接推导 runtime journal 路径（data/sessions/<session-id>.json）读全量调用参数。禁止在取得回执前对大数据目录做 search_files/全量 grep/目录名猜测（本集因此吃 3 次 60s 超时）。与 trace-first-party-tool-to-backing-store 卡互补：记录非本会话产出时才走代码反查存储路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:593:88aeb8cbd6c24d4bc78f
evidence_refs: learning:learn:dab81d90aefb
created_at: 2026-10-21T16:19:40.774768+08:00
updated_at: 2026-10-21T16:19:40.774768+08:00
---
## Trigger
search_records 按 ID 命中目标记录但正文被截断，且任务需要其完整权威文本（如『必须按批准内容实现、不凭记忆猜』）；事件流/记录元数据显示该记录由本会话早前的一次第一方工具调用创建。

## Discriminator
事件流条目同时携带：创建该记录的 session id + 时间戳，以及当前 run 自身 action_trace 的同一 session id → 该记录是本会话工具调用的产物，其原始回执（含载荷）已被会话 evidence ledger 索引，可按 ID 直接检索，无需先发现磁盘存储位置；截断只是展示层问题，不是数据不存在。

## Short path
- 从审批回执/截断命中记下记录 ID、创建工具名与时间戳；未知量：完整权威文本在哪。
- search_evidence 按记录 ID 检索：取创建工具的原始回执 evidence ref（常同时命中引用过全量参数的兄弟捕获）；未知量：回执载荷是否完整。
- 水合该 ref；若正文在提交时即被截断，沿同批命中的兄弟捕获，或用事件元数据里的 session id 直接定位 runtime journal（data/sessions/<session-id>.json）读全量调用参数——路径由已知 id 推导，不做目录枚举。
- 用记录库的截断预览做前缀逐字核对，一致即停止发现，进入实现。

## Stop conditions
- 已取得与记录库预览前缀逐字一致、且 ID/状态与审批回执匹配的完整文本。
- ledger 已证明载荷从未被完整捕获：切换一次 journal 或代码反查路线，不再反复换目录猜测。

## Verification
- 水合回执的记录 ID 与审批回执一致，文本前缀与 search_records 截断预览逐字一致。
- 若读 journal：其工具调用参数中的记录 ID 与回执封套一致。

## Counterexamples
- 记录由外部控制面/他人在别处创建（如人工 web 面板审批动作本身）：本会话 ledger 不含它，应按 ID 查登记簿记录（见 verify-external-state-change-via-registry-record-by-id）。
- 需要的是当前运行时活状态而非历史载荷（live 服务版本、进程配置）：ledger 回执是陈旧快照，应探活现场。
- 回执水合已完整且满足需求：立即停止，不再叠加读 journal（post-sufficiency 动作）。
- 环境没有 evidence 检索通道：退回代码反查存储路径路线（trace-first-party-tool-to-backing-store）。
