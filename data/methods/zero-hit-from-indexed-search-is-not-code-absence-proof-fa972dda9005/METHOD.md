---
method_id: zero-hit-from-indexed-search-is-not-code-absence-proof-fa972dda9005
name: zero-hit-from-indexed-search-is-not-code-absence-proof
description: 核验“某代码标识符是否存在”时，索引式搜索工具的零命中不构成缺席证据：本集它对 src 中真实存在的 _DECLARE_VERBS(L23)、matched_by(L233) 连续漏报，并诱导出“matched_by 只在数据文件、代码里没有”的错误中间结论。对代码符号形态的标识符，存在性核验的权威通道是对源码树的确定性 grep（或文件名命中→读 import 的 provenance 边）；零命中只应触发换通道，不应触发扩大枚举或写入“工作区无此标识符”类结论。数据/文档侧定位仍可用索引搜索（本集 jsonl 命中正常）。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:70:b4b5767442c2109a6d53
evidence_refs: learning:learn:9e3f0373c6e5
created_at: 2026-09-30T08:18:02.005549+08:00
updated_at: 2026-09-30T08:18:02.005549+08:00
---
## Trigger
需要核验此前轮次或他人声称存在的代码标识符是否真实存在及其定义位置，而索引式内容搜索返回零命中、或只命中数据文件时。

## Discriminator
标识符是代码符号形态（前导下划线/snake_case），且其“存在”已有此前轮次的具体引用作正向先验；零命中来自覆盖范围未知的索引搜索而非权威通道——工具结果与更强的已知正向证据矛盾时，应先怀疑工具覆盖缺口，而不是接受缺席结论或扩大搜索面。

## Short path
- 把全部待核验标识符合并成一次对源码树的确定性检索：grep -rn 'id1|id2|id3' src/，一次拿到定义文件与行号
- 或走已验证的 provenance 边：文件名搜索命中测试文件 → 读其 import 得实现模块路径 → 直接读该模块
- 数据落盘定位继续用索引式内容搜索（对数据文件有效）；通道各自命中后读源码确认符号本体即停
- grep 与索引搜索结论冲突时以 grep 为准，并把差异归因为工具覆盖缺口

## Stop conditions
- 权威通道已给出定义文件+行号并读到符号本体与语义，核验完成
- 确定性 grep 与索引搜索一致零命中，此时缺席结论方可成立

## Verification
- 任何“X 在代码中不存在”的中间结论写入报告前必须经确定性 grep 确认，不得仅凭单一搜索工具的零命中
- 对同一标识符交叉对比 grep 与索引搜索结果；差异必须能归因于工具覆盖（如索引未含 src），否则不得采信

## Counterexamples
- 索引搜索已在代码文件中命中该标识符：直接沿命中读取，无需再 grep
- 标识符是自然语言短语或主要存在于数据/文档（如 jsonl 审计记录）：索引搜索是正确通道，只 grep src 会漏掉数据侧真值
- 超大树且索引搜索已证明覆盖代码树（对控制词有命中）：其零命中可作有效缺席证据，不必强行全树 grep
- 标识符可能由拼接/别名动态生成：字面 grep 会假阴性，需改查构建点或运行时清单
