---
title: 撤回演进提案≠否定已验证事实：rejected_reason 必须把「事实」「撤回的修复方向」「重启条件」三者解耦写清
scenario: 对一条长期滞留 pending_review（无人推进、也无结论）的演进提案做撤回/标记决策时。最坏做法是直接删 JSONL 行，或只写一句「撤回本方案」了事——前者连带销毁支撑判断的实测证据与四套方案的漏报数据，后者让后续会话（包括我自己下一轮）只看到「rejected」，读不出「缺陷是否仍成立」，于是要么把它当已解决不再管，要么重启时又照原样再叠一层同型补丁。
root_cause: 提案状态机把「方案是否采纳」与「问题是否存在」压进同一个 status 字段，缺少事实在 rejected 后的存活表达；缺失后模型只能靠 rejected_reason 里的自然语言重建事实，措辞不严谨就永久丢失。
solution: 撤回时把 rejected_reason 写成三段式并保持可执行：(1) 撤回对象精确到「方案形态」而非问题域——本次撤回的是 _is_narrative_statement 词干×补语表形态，不是「完成标志门失效」这个问题；(2) 显式声明已验证事实仍然成立且仍未修复，并给出可复核的证据入口（文件+行为+观测面），使事实不随状态翻转而消失；(3) 写明重启条件与重启时应走的层级——根因层（结构化语义类别定义），禁止重启为同型的正则特判叠加。附加判据：若该提案是队列里最后一条待办，撤回本身就是有价值的信号治理动作，因为它清掉了会被后续会话误读为「待落地的修复方向」的排队项；但信号治理的收益不改变缺陷未修复的事实，两件事要在汇报里分开讲。
evidence: "EVO-20261013-60fe9141 于 2026-10-13T22:29:16 置 rejected，全库 pending_review 归零（rejected 总数 5）。rejected_reason 已按三段式写入：撤回 _is_narrative_statement 词干×补语表形态；_COMPLETION_MARKERS 含裸单字「了」导致 _is_ability_statement 豁免 0 触发这一事实仍成立、未修复；重启应走根因层方案。当前 src/llm_loop/feedback/validator.py:78 仍为 [\"已\",\"了\",\"成功\",\"完成\",\"did\",\"has \",\"have \",\"done\"]，缺陷仍在代码中。"
tags: [evolution, 提案撤回, rejected_reason, 事实保全, 根因层, 正则特判, 信号治理]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T22:31:21.211654+08:00"
updated_at: "2026-10-13T22:31:21.211654+08:00"
---