---
method_id: authoritative-parser-first-for-record-statistics-ca68b260488d
name: authoritative-parser-first-for-record-statistics
description: 审计/统计大量半结构化记录（front matter 卡片等）时，若契约或代码库已指名权威解析器——尤其当统计口径要求区分'字段显式标注 vs 解析器默认回填'这种正则无法恢复的信号——首版脚本就应 import 该解析器一次遍历全部记录，而不是先用正则重实现字段提取。本集首轮正则扫描把 125 张卡误判为'无 front matter'，被迫整体重做；另有一处 8 vs 6 的口算晋升数靠固化脚本重算才纠正。所有上报数字必须出自可重跑脚本（rerun rc=0 且输出一致），手工计数只作待验证假设。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:891:baacc4661fde090177fd
evidence_refs: learning:learn:63859381b06c
created_at: 2026-10-15T05:59:14.949287+08:00
updated_at: 2026-10-15T05:59:14.949287+08:00
---
## Trigger
需要对一批半结构化记录文件（markdown front matter / 经验卡 / JSON）产出分布统计或一致性审计，且任务契约或代码库中已存在具名权威解析器，或验收口径明确要求区分'字段显式存在 vs 默认值回填'。

## Discriminator
契约文本/任务回执里是否已点名权威解析器（本集任务回执明确写着'以代码解析器（ExperienceDocument.from_md）为权威口径……不用正则扫描'），或该解析器 API 本身能否输出 explicit/defaulted 之分。只要首版脚本出现自写正则或字符串切分来提取结构化字段，即为偏离信号，应立即改走具名解析器。

## Short path
- 从任务回执/契约中提取具名解析器，首版脚本直接 import 并用它一次遍历全部记录，得到 explicit vs defaulted 分布（未知量：权威口径下的真实分布）
- 对值得下钻的子集（如显式标注但状态异常的 11 张）继续用同一解析器的结构化字段做第二层统计，不切换口径
- 把全部计数固化进可重跑脚本，重跑 rc=0 且数字逐项一致后才写报告；口算/目测数字一律以脚本重算为准，差异处留修正声明
- 抽样反查验证口径：被计为 defaulted 的文件原文确无该字段、被计为 explicit 的确有，验证成立后停止

## Stop conditions
- 固化脚本重跑退出码 0 且输出与首次运行逐项一致
- 关键分布已由解析器口径给出，并与一次独立途径（ad-hoc 查询或 JSON 产物）交叉一致
- 报告中每个关键数字都能在脚本产物中逐一定位，无手工计数残留

## Verification
- 重跑脚本并 diff 输出，应为空
- 抽样核对：defaulted 文件原文中确无该字段，explicit 文件确有
- 凡修正过手工计数，在报告留修正声明并以脚本值为准

## Counterexamples
- 契约未指名解析器、文件由机器统一生成且抽样可验证——最小字段检查即可，不必引入重型解析器
- 具名解析器只适配另一版本 schema，或需实例化带写副作用的 store——只读任务应改用其纯文档级入口，而非回退到正则
- 只需在单个已知文件查一个字段——grep/正则足够且更便宜
- 解析器对当前语料大量 parse error——先验证解析器适用性再定口径，不能默认权威
