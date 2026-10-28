---
method_id: gate-negative-existence-claims-on-partial-coverage-550377503e78
name: gate-negative-existence-claims-on-partial-coverage
description: 对长参考文档做分段/有界读取以验证某命名实体、事件、字段是否存在时，只要回执的 coverage/range 元数据仍标 source_partial、complete:false 且总长度未知，就不得下'不存在/未见记载'的文档级否定结论，也不得据此删除或降级内容。'我没读到 X'只证明已读区间没有 X；应把否定观察暂限定在已覆盖区间，继续按 next_start 顺序分页到 complete，或对全源做定向搜索/权威索引核对后再裁决。否则部分覆盖会冒充全量证据，产生错误裁决，事后被迫整篇重读翻案并重做下游修改。
status: active
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:bb10f7a5-7006-4dd0-b800-13d0f9a35fdc:40:74ab4b4428d06681e983
evidence_refs: learning:learn:e4f5bf1177b3
created_at: 2026-10-18T16:55:02.307044+08:00
updated_at: 2026-10-18T23:33:42.217470+08:00
---
## Trigger
在单一权威长文档（官方 reference、规范、schema）上以分页/截断方式验证'某命名实体/字段/选项是否存在或是否支持某行为'，即将据此发出否定裁决（不存在/未记载/建议删除或标存疑），且当前 evidence 回执可见 coverage=source_partial、complete=false、总长度未知（如 text_char:0-? 且 next_start 递增）

## Discriminator
读取回执中的覆盖元数据本身就是判别事实：complete 是否为 false、coverage 是否标 partial、总量是否未知。只要为 false，否定性观察的证据范围仅限于已读区间，不足以支撑文档级'不存在'；该事实在首段读取时即可见，足以在过早下结论前触发门控。

## Short path
- 读取首段后先检查 coverage/range 元数据，确认总长度与 complete 状态，建立'否定结论需待覆盖完成'的门控
- 继续按 next_start 顺序分页；每段中目标项'未出现'只记为该覆盖区间的临时观察，不升级为文档级结论
- 若目标项出现，交叉核对同文档中相关表格（定义表与行为/决策/超时表）确认其语义边界，避免只见存在不见能力范围
- 分页到 complete:true（或对全源做全文搜索/核对权威索引）后才输出'不存在'，并在结论中注明已覆盖的总量
- 若全量读取成本过高，把否定结论显式降级为'已读 N 字符内未见'并说明剩余未读部分，交由用户决定是否继续

## Stop conditions
- 分页到达 complete:true 或确认已到源末尾
- 对该源的全文搜索或权威索引返回确定的无命中
- 目标问题已被已读区间的定义性内容（含其交叉行为表）完全回答，且不依赖文档其余部分

## Verification
- 最终否定结论附覆盖依据：已读/总字符数，或全源搜索无命中的回执
- 肯定结论引用具体表格/章节原文，并与同文档中该条目的行为/决策表交叉一致
- 对照先前基于部分覆盖的临时结论，逐条确认已更新或撤销，无残留旧裁决

## Counterexamples
- 目标项受权威目录/索引约束只可能出现在已完整读取的章节（如按字母序索引已读完对应区段），可下区间级否定结论，无需读完全文
- 首次读取即 complete:true，内容一次性全量返回，不存在部分覆盖问题，可直接裁决
- 问题语义已被已读部分定义性回答（如某行已明确该事件对退出码的处理），不必为回答它读完全文
- 源过长且易变、又无分页/搜索工具时，正确做法是输出带明确覆盖边界的临时结论，而不是无限读取
