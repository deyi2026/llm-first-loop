---
method_id: read-pagination-coverage-ledger-under-truncation-cap-bab7d939e534
name: read-pagination-coverage-ledger-under-truncation-cap
description: 读取长文档时，若工具回执携带 range 元数据（start/count/next_start/complete）且已观察到单次负载截断上限，就把每份回执当作覆盖账本：只对未交付的缺口发起不重叠读取，块大小控制在截断上限内；回执并集覆盖全文（或任务所需区间）即停止。避免对已标记 complete 的区间重复读取、以及反复用超限 limit 撞同一次截断。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:1:a8c99c9d23507f74d21d
evidence_refs: learning:learn:565e1c20e316
created_at: 2026-10-10T08:24:52.957196+08:00
updated_at: 2026-10-10T08:24:52.957196+08:00
---
## Trigger
对同一长文件连续多次读取，回执带 start/count/next_start/complete 元数据，且此前读取已暴露负载截断（如 8192 字符截断）或已出现重叠/重复读取。

## Discriminator
回执显式声明已交付区间与 complete/next_start 标志，加上已观察到的截断上限，使『还缺哪些行』成为机械计算而非记忆问题。本集第二次读取（125 行起、limit 270）回执已标 complete=true、next_start=null 并覆盖到 392 行，其后对 248-392、332-392、155-247、155-183、184-247 的读取全部与该 complete 区间重叠，且 duplicate_calls=1。

## Short path
- 首次读取：解决未知量『文件多长、这次实收到哪』——记录总行数、实收末行、观察到的截断上限。
- 由截断上限与实收行数估算安全块大小，使下一次请求的预计负载低于上限。
- 只对未交付缺口发起读取：起点取上一回执 next_start，区间不与任何已 complete 区间相交。
- 每张回执后更新已覆盖区间并集；并集覆盖 [1..总行数] 即停止读取，转入分析。

## Stop conditions
- 各回执区间并集覆盖全文且无缺口，或已覆盖任务所需的目标区间
- 任务只需特定章节且该章节已完整交付，无需全文覆盖

## Verification
- 汇总各回执 start/count/complete，检查并集无 gap、无 overlap，且 version_token/blob_sha256 全程一致（读的是同一版本）
- 最终意见中引用的每条事实都能定位到已交付区间内的具体行

## Counterexamples
- 文件一次读取即可完整返回（无截断迹象）：直接读一次并分析，不建覆盖账本
- 任务只针对已知行号/章节：只读该区间即可，全文分页属过度覆盖
- 回执不含 range/complete 元数据且从未观察到截断：判别器不存在，应改用 grep/目录定位目标章节
- 文件存在并发写者、version_token 变化：区间账本失效，须按新版本重新读取（属 fresh-read-authoritative-record 场景）
