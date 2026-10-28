---
method_id: truncated-receipt-cannot-ground-aggregate-claims-986ccdb329db
name: truncated-receipt-cannot-ground-aggregate-claims
description: 把回执信息写成聚合断言（'共N个''档位为a/b/c''全部X''最大Y'）前，检查证据回执是否带截断标记或已知返回上限：截断回执只支持存在性/示例断言，不支持任何聚合值，因为截断可能恰好砍掉未见的尾部成员。聚合数字必须升级到完整权威源（registry直读、带total字段的响应、翻页聚合）后再落笔。本集初稿从被截断的model_catalog回执推出'15个模型、5个价格档'写进正文与两张图，审查FAIL后用load_registry重取得28个模型、档位4/7/9/8，正文+图2+图3全部重做。与fresh-read-authoritative-record卡的区别：那是并发写导致的新鲜度问题、发生在成稿一刻；这里是证据完整性问题、应发生在草稿期数字落笔前。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:207cc107-c78d-4833-8de6-261570f7985a:0:06f6851ff46065788c95
evidence_refs: learning:learn:f85bc5191469
created_at: 2026-10-15T00:46:28.696542+08:00
updated_at: 2026-10-15T00:46:28.696542+08:00
---
## Trigger
准备把工具回执（文件/记录/API/日志列表）中的信息写成数字、总数、完整枚举、最值或'全部'类断言，且该产物将进入对外面（发布文章/报告/不可逆动作）；或审查闸正在核查数字可核性时。

## Discriminator
两条同时观察成立即阻断落笔：①来源回执带可见截断标记（如'截断显示前N'）或已知分页/返回上限，即证据是部分的；②断言是聚合值（count/total/完整枚举/max），其真值依赖可能被截断砍掉的成员。存在性或示例性断言（'至少有一个''例如X'且X在已显示部分）不受此限。

## Short path
- 起草每个聚合性数字时，先定位其来源回执并检查是否存在截断标记/返回上限
- 若回执截断且断言为聚合值：将该数字标记为unknown，不在正文或图中填入推测值
- 对每个unknown聚合值升级取完整源：权威registry直读、带total字段的响应或翻页聚合，一次取齐
- 从完整源重推所有数字（含图表标注），并记录provenance
- 再进入审查/发布闸；审查时逐数字反查来源完整性

## Stop conditions
- 全部聚合性数字均溯源到无截断回执、自带权威total的响应或完整registry读取
- 断言仅为存在性/示例性，且被引用成员确实出现在回执已显示部分
- 数字不会进入对外产物（纯内部草稿），可推迟到成稿前统一补取真值

## Verification
- 逐个数字反查来源回执：确认无截断标记，或响应自带total且与引用值一致
- 独立审查闸对数字可核性给出PASS（本集正是该检查拦下了15→28的错误）
- 图中标注数字与正文数字同源同值

## Counterexamples
- 回执自带权威total（如响应写明total=28、仅展示前15条）：total可直接引用，无需再取全量
- 断言是存在性或举例（'至少存在一个''例如模型X'）且该成员在已显示部分：部分回执已足够
- 纯探索/内部草稿阶段且数字不会离开工作区：可先占位，成稿前一次性补取，不必每次读到列表就全量拉取
