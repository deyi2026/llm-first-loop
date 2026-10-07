---
method_id: verified-ledger-single-read-over-evidence-paging-975c835fd129
name: verified-ledger-single-read-over-evidence-paging
description: 需要总结/报告近期工作时，若 list_evidence 元数据显示一个 freshness=verified_current 的账本文档加一个仍可查询的 live 源（如 running job），就把事实重建压缩为对这两个权威源的一次性完整读取/查询：用 header 行号做一次 ranged read 拿全部状态，用一次直接查询拿在途状态。evidence hydration 只用于识别身份，不对已知的可查询源做截断分页窥视后再用直接查询重复同一事实；完整读取状态表后也不再 grep 复确认同表数据。只有账本不覆盖的未知量才补读对应产物。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:1444:4903f72615792e6ed12d
evidence_refs: learning:learn:7efdfc039b6a
created_at: 2026-10-07T12:09:46.347349+08:00
updated_at: 2026-10-07T12:09:46.347349+08:00
---
## Trigger
用户要求总结/汇报近期工作；证据清单已给出带 freshness/source/coverage 元数据的条目，其中含单个 verified_current 的账本类文档和一个可再次直接查询的运行时源（如 running job）。

## Discriminator
两处当时可见事实：(1) 清单中 edit_file 账本条目标注 freshness=verified_current → 直接读该文档即为可信现状；(2) runtime 证据条目 freshness=unknown 且 hydration 回执自带 range.complete=false / next_start>0 截断标记、其 source 是可再查询的 live tool → 分页窥视只能识别身份，内容应由一次直接查询取得；一次 ranged read 已含完整状态表时，同表数据无需二次 grep。

## Short path
- list_evidence：用 freshness/source 标签识别'账本文档（verified_current）+ 在途 live 源'两类来源；未知量=这段时间做了什么、什么还在跑
- 对文档做一次 header 索引（grep -n '^##' 或已见目录）得到节→行号映射；未知量=文档结构
- 一次 sed ranged read 覆盖里程碑/决策/闭环节；未知量=完成了什么、决策是什么——此步后状态表已完整在手
- 对 job 源做一次直接状态查询（含命令、是否结束）；未知量=在途工作状态——此查询取代对 job_output evidence 的分页窥视
- 仅对账本未含的量化指标补读对应产物一次（如 baseline 报告）；未知量=精确数字
- 成稿停止：每条 claim 对应一次权威源读取/查询回执，不做同表复确认

## Stop conditions
- 账本 ranged read + live 查询已覆盖用户问题的全部未知量
- 每个待写 claim 都能指向一条权威源读取/查询回执

## Verification
- 成稿后核对：无 claim 仅由截断 hydration（complete=false）支撑
- 全文不存在对同一状态表的第二次确认调用（完整读取后再 grep/sed 同表）
- 若账本文档存在并发写者风险，读取时的 version_token/stat 仍为 verified_current，否则重读

## Counterexamples
- 账本 freshness=unknown 或存在并发写者：不可当唯一事实源，须在成稿时 fresh-read 权威记录（衔接 fresh-read-authoritative-record 方法）
- 用户要的未知量账本未覆盖（未归档的失败原因、精确测试计数）：必须读原始回执/产物，不能只信账本叙述
- 证据清单无单一账本（多并行工作流且无文档）：逐条 evidence 审阅合理，此时分页 hydration 是正当手段
- evidence 的 source 已不可再查询（仅存 recovery_handle）：内容只能靠 evidence 本体，应继续翻页而非'直接查询'
