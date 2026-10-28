---
method_id: terminal-job-receipt-truncated-fetch-unread-tail-only-9392a4252978
name: terminal-job-receipt-truncated-fetch-unread-tail-only
description: 长跑命令到达终态（wait 终态回执已给 exit code）后，要从长 stdout 报告逐字计数/汇总行时，若输出回执首视图在远小于总行数处截断、且 range 元数据已给总行数与 complete:false，第一个未知量不是『取回完整输出』而是『未读尾部区间里的汇总行』：用回执 count 直接定位尾部行区间，一次 ranged 读取同时取得汇总计数、最终结论行、evidence_ref 与完整性哈希；exit code 以终态回执为准，不从日志文本推断。不重取已展示的头部，不为『看全』而分页。区别于『已完整读取文件的锚点段重读』：本方法针对首次读取即截断的不可变终态证据，只补未读余量。
aliases: job输出被截断怎么看汇总, 长日志只显示前面几十行, 门禁日志取尾部计数, 截断输出直接读尾巴, 终态日志汇总行在哪
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1c90ac6d-5545-4dee-a0ca-b6b26a501140:1:f029eb2945db8db6cbd9
evidence_refs: learning:learn:6e9f13f77207
created_at: 2026-10-27T13:05:07.135667+08:00
updated_at: 2026-10-27T13:05:07.135667+08:00
---
## Trigger
后台 job 已到终态（wait 回执含 exit code），用户要求报告精确计数/汇总（如静态债 ratchet 计数、pytest passed/failed、最终结论行），而 job_output/证据首视图在总行数的一小部分处被截断，回执元数据给出总行数、next_start 与 complete:false

## Discriminator
exit code 已由 wait 终态回执权威确认；输出回执已展示头部且标明总量（如 604 行只见约 40 行）；所需报告事实全部是日志尾部的终态汇总（阶段汇总行与最终结论行天然靠近日志末尾）——唯一未知量就是未读尾部区间 [已见末行, count]，头部重取不产生新信息

## Short path
- 以 wait 终态回执锁定 exit code，作为报告中退出码的唯一权威来源
- 从 job_output 回执读出总行数与截断位置，计算未读尾部区间（如 start=count-80）
- 对该区间发一次 ranged 读取/hydration，取回汇总计数行与最终结论行，同时记录 evidence_ref/blob_sha256 供引用
- 把用户点名的报告字段（计数、错误、证据引用）逐项与已取得证据核对，齐则停止

## Stop conditions
- 用户要求的每个报告字段（exit code、原始计数、错误、引用）均有权威来源支撑后立即停止，不再分页其余行
- 若一次尾部读取未覆盖所需行，按 next_start 或可见分节标记再补一次有界区间，绝不回到 offset 0 重读头部

## Verification
- 尾部读取回执的 blob_sha256/range_sha256 与总回执一致，计数字段逐字抄录进报告
- exit code 只引用 wait/job 终态回执，不用输出最后一行文本推断

## Counterexamples
- 需要的事实在日志中部（首个失败用例、特定报错栈）而非尾部汇总时，盲取尾部会漏；应按可见分节标记（如 ═══[n/5]═══）定锚再取对应区间
- 回执已 complete:true 且所需字段都在首视图内时，任何再次读取都是 post-sufficiency 动作
- 要下『输出中不存在 X』类否定结论时，只读尾部区间覆盖不足，不得据此断言不存在
