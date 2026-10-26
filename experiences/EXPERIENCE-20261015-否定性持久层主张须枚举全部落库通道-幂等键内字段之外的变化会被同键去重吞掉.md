---
title: 否定性持久层主张须枚举全部落库通道，幂等键内字段之外的变化会被同键去重吞掉
scenario: "设计文档 v2 断言“工具回执不含版本信息、事后无法从事件流恢复读取时刻版本”，依据仅是工具迹行（tool_cycle.py:737-745）四字段无回执内容。外部审查指出 tool_cycle.py:764 经 _append_message_event 以 message.appended 落库工具回执，events.py:228-243 载荷确实含 content。核验后确认：主张过强，应收窄为“无统一、可靠的结构化版本凭据”（message.appended fail-open 于 244-247 行、正文可被收敛附加段改写于 703-709 行，不能作凭据），但设计结论（新增 knowledge_read 打点）仍成立、理由更新。"
root_cause: ""
solution: "下否定性结论前枚举同一数据的全部落库通道：工具迹行、message.appended 消息事件、tool_octet 观测、WAL/恢复路径，逐一确认“缺失”或“不可靠”后再陈述。若部分通道存在但不可靠，用“不存在统一可靠凭据”而非“完全无法恢复”表述，并逐条列出不可靠原因（fail-open、可变写、无结构化字段）。相关反例模式：把语义字段（如使用决定）放进幂等键，键外字段（如评价）改变会被同键去重吞掉——键内字段选择决定哪些更正无法表达。当前性验证：grep -n \"build_message_payload\" src/llm_loop/core/loop/events.py 确认载荷仍含 content 参数后再引用本卡。"
evidence: "events.py:216-243（_append_message_event 载荷含 content，本轮 read_file 直接核验）；events.py:244-247（fail-open）；tool_cycle.py:737-745（工具迹四字段）、703-709（收敛附加段改写 result.content）、764（工具回执经 _append_message_event 落库）——均本轮 read_file 直接核验；文档修订前后快照 artifact://v1/6bf4e847865c4cf3b55dfca1dfa81381 与 artifact://v1/a21984e403874b6d92b3d58bf19c3d69。"
tags: [核验纪律, 否定性主张, 持久层通道枚举, 幂等键设计, 设计文档评审]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T21:02:06.579830+08:00"
updated_at: "2026-10-15T21:02:06.579830+08:00"
---

核验“某信息不存在于持久层”类否定性主张时的通道枚举纪律：必须枚举全部写入通道再下结论，只查主通道会得出过强主张。当前性验证：grep -n "_append_message_event" src/llm_loop/core/loop/engine_services/tool_cycle.py 应仍命中 764 行附近；grep -n "message.appended" src/llm_loop/core/loop/events.py 应仍命中 243 行附近。