---
method_id: primary-artifact-before-evidence-store-retrial-dbcb75b044d5
name: primary-artifact-before-evidence-store-retrial
description: 当要确认的域事实（如某服务 endpoint 与上次的可达性结论）来自先前调查，而 evidence/记忆系统的条目显示其只是对本地 artifact 的命令记录（source 为 execute_command 等工具观测、标签不透明、低 limit hydrate 只返回命令行）时：把元系统当索引用一次，从命令的目标路径定位主文件并直接 grep/read 取得基线；随后仅针对基线中标注的未知量做分层实测（权威公共解析器 DNS、同类对照主机、解析记录结构检查），定位根因即停。避免在元系统内换关键词重搜或逐条低 limit hydrate。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:67:62175a134e16f6d6d24c
evidence_refs: learning:learn:c87a945e0a77
created_at: 2026-09-18T02:12:42.080918+00:00
updated_at: 2026-09-18T02:12:42.080918+00:00
---
## Trigger
需要复用先前调查的结论或验证某域事实，且 evidence 列表条目均为工具操作快照（无 domain content 条目）、命令参数中可见本地文件路径；或从上下文可推断存在承载结论的报告/产物文件。

## Discriminator
evidence 元数据中 source=execute_command:command#xxx（工具观测快照、freshness unknown），且 hydration 仅返回命令头部而参数里出现仍存在的文件路径——证明事实的权威载体是可直接访问的主 artifact，元系统只是低产出的间接副本；对该副本做关键词重搜或逐条小范围 hydrate 无法产出域事实。

## Short path
- 对 evidence 做一次 list/search，判断条目性质：是外部域内容（直接 hydrate），还是对本地文件的操作记录（转下一步）
- 从操作记录中命令的目标路径定位主 artifact，直接 grep/read 关键词，取得基线：文档化 endpoint、上次结论及其标注的不确定性（如'超时，原因未知'）
- 仅针对基线中标注的未知量设计分层实测：先用权威公共解析器查 DNS，同时用一个同类（同 CDN/同协议）对照主机排除本地网络因素
- 若对照通过而目标异常，检查解析记录本身的结构问题（仅私有地址、缺 A/AAAA 记录）；仍存疑时一次强制 SNI 连已知边缘节点即可终止枚举
- 根因定位后停止探测，回写主 artifact 中被推翻的结论，并基于根因给出可达的替代路径

## Stop conditions
- 主 artifact 已给出基线事实，且分层实测已把基线中的不确定性收敛为单一根因（结构性不可达 vs 本地网络受限）
- 解析记录自身的结构异常已足以解释不可达，不再枚举更多探测变体（换端口、换路径、换超时等）
- 发现主 artifact 已不存在时，停止 grep 分支，转向对最相关 evidence 做高 limit hydration（此时快照是唯一副本）

## Verification
- 确认最终事实与主 artifact 记载一致，且其中被新证据推翻的结论已被更新
- 不可达类结论需同时覆盖三层：目标解析是否异常、本地网络是否正常（对照通过）、目标是否结构性拒连
- 确认所依据的 evidence source 标签确实指向当前仍可访问的本地文件（路径存在且非过期 tmp）

## Counterexamples
- 主 artifact 已被清理（如 tmp 目录过期删除）——evidence 快照是唯一真值，正确路径是高 limit hydration 而非 grep 文件
- 用户问的是'先前做过哪些操作/调用了什么'这类过程事实——evidence store 本身就是主数据，直接搜索是正路而非绕路
- evidence 条目 is_domain_content=true（外部抓取的网页/接口内容）——该 evidence 即主数据源，应直接 hydrate 它而不是去找背后的文件
- 文件处于 versioned 语境且可能被并发修改——当前文件内容不可盲信，应以带版本 token 的快照为准
