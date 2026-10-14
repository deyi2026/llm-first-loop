---
method_id: trace-first-party-tool-to-backing-store-on-truncated-receipt-521a350ff02b
name: trace-first-party-tool-to-backing-store-on-truncated-receipt
description: 当第一方工具（本 repo 实现的 introspection/search 类工具）回执命中目标记录但内容截断，而你需要完整字段或权威状态时，不要对大数据目录做全量 grep/search_files 或猜目录名。回执命中本身证明权威 store 存在，且其实现就在本仓库：先定向 grep 该工具实现，读出存储路径常量（本集为 audit 目录下 jsonl），再按 ID 精确过滤读取。本集先经历两次 60s 超时与 submissions/drafts 目录猜测，改走代码侧后 3 次 grep 即定位 store，省去全部文件系统枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:1024:ff468d3e26412d7ecb71
evidence_refs: learning:learn:990a2d118bad
created_at: 2026-10-14T19:47:20.139291+08:00
updated_at: 2026-10-14T19:47:20.139291+08:00
---
## Trigger
第一方工具回执命中目标记录但内容截断，需完整内容或权威状态字段；且数据目录大、全量内容扫描已出现或易出现超时

## Discriminator
两条当时已知事实：(1) 回执来自本 repo 自己实现的工具，实现代码可 grep，回执命中即证明权威落盘 store 存在；(2) 该环境下全量 grep/search_files 已 60s 超时，证明宽扫描在此不可行——两者共同把候选空间缩成『沿工具实现找存储路径』这一个下一跳

## Short path
- 收到审批回执后先用 search_records/event_stream 核实两条 EVO 的状态与是否已有执行记录（未知量：状态 + 防重复执行）
- 回执截断时不猜 data/ 子目录、不做全量扫描：在 src/ 内定向 grep 工具实现，读出 store 路径常量（未知量：权威存储位置）
- 按 ID 从 store 文件（jsonl）精确过滤读取完整记录（未知量：批准范围、impact_scope、requires_human）
- 状态=accepted 且 evolution_exec 流无同 ID 记录 → 立即转入实现，停止一切发现类动作

## Stop conditions
- 已从工具实现指认的权威 store 按 ID 取得完整记录，且状态与审批回执一致
- 已确认无既有执行记录后，不再做任何额外的目录/文件系统发现

## Verification
- store 中读出的 id/status 与审批回执的 EVO ID 及 web 面板新状态逐一一致
- evolution_exec 流中确无同 ID 记录，排除重复执行
- 实现源码中的 store 路径常量与实际读取路径一致（同源）

## Counterexamples
- 记录来自外部第三方服务（本地无实现可 grep）→ 代码侧溯源不可用，改用该工具自身的详情/分页/limit 接口取全文
- 工具本身已提供按 ID 取全文或 raw 模式 → 直接用工具参数，不必定位落盘文件
- 落盘是带 flock 的活库或有审计/PII 约束，绕过工具直读文件有一致性或合规风险 → 用工具 API 或官方导出命令而非裸读文件
