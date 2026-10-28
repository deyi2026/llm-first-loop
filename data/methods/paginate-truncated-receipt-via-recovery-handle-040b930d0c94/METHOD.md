---
method_id: paginate-truncated-receipt-via-recovery-handle-040b930d0c94
name: paginate-truncated-receipt-via-recovery-handle
description: 工具回执返回 success 但正文被机械截断，且回执自带 recovery/evidence 句柄与分页元数据时：不重跑生产命令、不重复调用原工具，而是对同一持久化 blob 做分页恢复读取。三个判别要点：range.complete 是相对类型的（单行 JSON 投影下 line 完整≠字符完整）；applied_limit==requested 且 bounded_by_server_max=false 说明页大小由客户端决定，可一次探测更大页以减少调用数；逐页校验 blob_sha256 一致与偏移连续，直到 complete 且无缺口才成稿。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0d161300-6c3e-42f8-b7e0-d5b2372425cc:26:4ef83561255cf27caf65
evidence_refs: learning:learn:d91ad398e80d
created_at: 2026-10-18T00:33:23.747048+08:00
updated_at: 2026-10-18T00:33:23.747048+08:00
---
## Trigger
原生工具（如 job_output）回执为 success，但输出正文被机械截断（内容在 token 中途被切断，或可见字符数远小于回执声称的行数/总量），且回执显式给出指向同一持久化结果的 recovery_ref/evidence_ref 及 range 分页元数据（start/applied_limit/bounded_by_server_max/next_start/complete/integrity）

## Discriminator
截断发生时回执里已存在的事实：1) recovery_ref 指向同一 immutable blob（origin_run_generation 与 blob_sha256 稳定），即完整真值已持久化，无需再执行；2) 每页元数据中 applied_limit==requested_limit 且 bounded_by_server_max=false，页大小是客户端自选而非服务器上限；3) 首次 line 类型恢复回执 complete=true 但可见内容仍在字符维度被切断（N 行投影为单行长 JSON），说明 complete 是相对 range 类型的

## Short path
- 调用一次原生工具，记录 status/exit_code、回执声称的输出规模、recovery_ref 与 blob_sha256
- 确认截断后不再重跑任务、不重复调用原工具：打开 recovery_ref，读取同一持久化 blob 的恢复视图
- 按截断维度选择 range 类型（字符截断用 text_char 而非 line）；先用一次较大 requested_limit 探测，若 applied<requested 则退回以 applied 为页大小
- 顺序分页直到 complete=true 且 next_start=null；逐页核对 blob_sha256 与首页一致、相邻页偏移严格衔接无缺口
- 从已全覆盖的 blob 提取用户所需全部事实（各阶段结果、通过/跳过/失败计数、复核段、exit_code），与已知 durable 终态对齐后成稿停止

## Stop conditions
- 用户所需全部事实均已从 SHA 一致、偏移连续、末页 complete=true 的完整 blob 中提取，且 exit_code/state 与既有 durable terminal event 双向吻合
- 用户明确要求『完整输出』时必须读到末页 complete=true，不得以首屏摘要或部分页代替全覆盖

## Verification
- 每页 blob_sha256 与首页一致；相邻页 start 严格等于上一页 end；末页 complete=true 且 next_start=null，总覆盖等于 blob 实际大小
- 报告中的 exit_code、任务状态同时与回执头部及任务已有 durable 终态记录一致；全程未触发任何生产性命令（无重跑、无修改）

## Counterexamples
- 回执截断但未提供任何 recovery 句柄：此时一次带范围参数的重复读取或改用支持 range 的接口是合理的，『绝不重调原工具』不再适用
- blob 极大且用户只需少数事实、环境提供 grep/检索设施：定向检索目标段落优于全量线性分页
- 截断的根因是任务仍在运行、输出尚未写完：分页恢复无法补全不存在的内容，应先查 job 状态再决定
- applied_limit 被 bounded_by_server_max=true 约束：加大 requested_limit 无效，直接按服务器上限页大小顺序分页即可
