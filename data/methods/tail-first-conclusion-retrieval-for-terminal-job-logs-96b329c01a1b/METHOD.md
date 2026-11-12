---
method_id: tail-first-conclusion-retrieval-for-terminal-job-logs-96b329c01a1b
name: tail-first-conclusion-retrieval-for-terminal-job-logs
description: 后台命令已达终态（wait 回执已给出 exit code 与 state）后，需从捕获输出如实报告失败结论时，不要从行 0 顺序分页：先用大偏移 text_char 探针定位 blob 尾端（count=0 且 complete=true 即越界），回退读尾部 2~4K 字符拿结论行（失败阶段、错误计数、退出原因）；中段首次确认重复同质 stack-trace 块后不再读该区间；需前面阶段判定时按阶段头锚点定点回补或复用首次预览。行投影受字符视图上限截断，大 blob 改用字符偏移投影。终态 exit code 以 wait 回执为准，与日志尾互相印证。
aliases: CI 挂了先翻日志最后一屏, 报错刷屏只取汇总与计数行, 退出码非零后从结尾倒查原因, 长输出先探末尾再定点回看, 跳过重复报错堆栈读结论
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bc99ff08-658c-4355-afd2-b4b2ecc29011:20:ff8fcaabea8e81bbf777
evidence_refs: learning:learn:fa51b7dc36e0
created_at: 2026-11-12T13:00:23.707294+08:00
updated_at: 2026-11-12T13:00:23.707294+08:00
---
## Trigger
后台作业已到终态（wait/job 终态回执带 exit code 与 state），需从其长捕获输出中提取失败结论、阶段判定或最终计数用于如实报告，且输出长度超过单次视图

## Discriminator
终态与 exit code 在读取日志前已由 wait 回执确知；多阶段门禁/测试日志的结论行、错误汇总与退出原因集中在尾部；首段读取即可见阶段头结构，第二段读取即可见中段为大量重复同质错误块（同一 stack trace 复现数十次）；行投影内容受字符上限截断而字符投影不受

## Short path
- 终态确认后不做顺序分页：先发一次大偏移字符投影探针，count=0 且 complete=true 即为越界上界，据此回退读尾部 2~4K 字符
- 从尾部提取结论要素：最后到达的阶段判定、错误/测试计数行、退出原因
- 若还需前面各阶段判定，用阶段头锚点定点读，或直接复用首次 job_output 预览中已含的部分，不顺序扫描
- 中段首次确认重复同质错误块后，跳过同质区间不再分页
- 以 wait 回执的 exit code 与尾部结论互相印证，一致即停止读取并进入归因报告

## Stop conditions
- exit code（回执）、失败阶段、错误类别、最终计数/结论行均已取得且相互一致
- repeat_guard 已提示同一 evidence_ref 多次读取——除定位末尾的探针外不得继续分页
- 尾部结论已足以支撑归因（如失败发生在测试收集之前、错误全部为环境性写拒绝）

## Verification
- 报告中 exit code 与 wait 终态回执逐字一致，不凭日志猜测退出码
- 引用的结论行/计数与 blob 原文一致，且多次读取的 blob_sha256 相同（同一事实源）
- 宣称『已读完整』时，确有覆盖全区间的 complete=true 证据，而非仅首尾抽样

## Counterexamples
- 根因位于日志前段（早期配置错误、首个报错即答案，尾部只剩重复噪声）时应头部定点回看，不能只读尾
- 审计/合规任务要求逐行完整核验日志时不得跳读或抽样
- 日志很短（小于单次视图上限）时一次读取即可，探针与定点回补纯属多余
