---
method_id: anchor-and-tail-retrieval-on-truncated-ordered-ci-logs-64a37bedf123
name: anchor-and-tail-retrieval-on-truncated-ordered-ci-logs
description: 线性有序长日志（CI 门禁/构建输出）的 job_output 回执被截断在中段、汇报仍缺尾部结构性汇总（各阶段统计行、最终 ✅/verdict 行、全量 pytest 数字）时，不做无锚点的中段偏移顺扫（本集 12000→33000→45000→49000→61000→65000 六次水合），也不拿记忆里的旧数字当搜索词（"394 passed…" 必然 miss）。判据：wait 回执已证 exit 终态 ⇒ 尾部 verdict 行必然存在；可见部分已暴露可逐字复制的锚点约定（阶段标记 [k/N]、结尾 verdict 短语）。先锚点串内容检索，miss 再从大偏移尾向水合并以 next_start/complete 只在目标阶段区间收敛。与 char-offset-bisect 互补：那是字段位置未知时的二分，这是位置可由日志结构先验直接钉死时的锚点/尾向取数。约 7 次检索可压成 2-3 次。
aliases: CI日志截断后怎么找最终统计, 长日志只看结尾verdict行, 截断job_output取pytest统计, 别从头翻CI日志找结论行, 按阶段标记k/N搜日志锚点, 用日志尾部汇总代替全量翻页
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7829a2a7-20f2-4af4-be35-c245f9f92b74:0:57beacfce5db0e4f6eae
evidence_refs: learning:learn:f9c6d4de4c49
created_at: 2026-10-24T21:29:34.264970+08:00
updated_at: 2026-10-24T21:29:34.264970+08:00
---
## Trigger
后台长命令已达真实终态（exit code 已由 wait 回执证明），但 job_output 回执显示被截断在中段（如 743 行只显示到阶段 3/4），而汇报仍缺日志尾部的结构性汇总字段：各阶段统计行、最终 ✅/verdict 行、全量 pytest 数字

## Discriminator
日志是线性有序的，且可见部分已暴露结构锚点约定：阶段标记 [k/N]、每阶段标记后紧跟统计行、脚本结尾 verdict 行；wait 回执的 exit=0 终态 ⇒ 结尾 verdict 行必然存在于日志尾部。目标字段位置可由结构先验钉死，无需从头顺扫或盲目二分；另外可见回执已给出本次 run 的真实统计样例（如 tier0=319 passed），足以否定用上轮数字（394）当检索键

## Short path
- 从 wait 终态回执记账 exit code（本例 exit=0），未知量收窄为 stdout 内的尾部汇总字段
- 逐字复制可见回执中的锚点串（阶段标记 "[5/5]"、verdict 短语如 "全链路通过"/"✅"）做内容检索，直接命中阶段 5 统计与最终 verdict 行
- 若检索 miss：以远大于已显示范围的大偏移做尾向水合，用回执的 next_start/complete 标志只在目标阶段区间内收敛；禁止从中段偏移开始 4k 步进顺扫
- 汇报中每个统计字段回指本次 run 的一条回执证据；五阶段标记 + exit code + 全量 pytest 数字 + 最终 verdict 行齐备即停

## Stop conditions
- 五阶段标记、真实 exit code、全量门禁 pytest 统计、最终 verdict 行均有本次 job_output/检索回执出处
- 不得以记忆或上轮数字（如 394）作为本次搜索词或结论；tier0 预检统计不得冒充全量门禁统计

## Verification
- 汇报中每个数字可指回一条本次 run 的证据（wait 回执 exit、job_output 显示段、search/hydration 命中段）
- 最终 verdict 行与 wait 回执的 exit code 语义一致（✅ 全链路通过 ⇔ exit=0）

## Counterexamples
- 目标事实是分布式出现（如统计全部 warning 出处、每处 base_url），尾部锚点无用，顺序分页/顺扫才合理
- 日志为并行交错的原始流（xdist worker 输出）且无阶段汇总约定，尾部不保证含所需字段，应按具体测试名/错误串锚点检索
- job_output 回执未截断（完整显示）时无需任何二次检索，直接汇报
- 检索工具只支持精确匹配且可见部分没有可复制的锚点串时，锚点搜索不可用，只能尾向水合+complete 标志走查
