---
title: self_evaluate 的 trigger 参数为枚举值，传自由文本会参数预检失败——陌生工具首调前先查 Schema
scenario: "会话轮次结束后需触发自我评估时，首次调用 self_evaluate 传入自由文本 trigger（\"会话轮次结束后的主动自我评估：…\"），被参数预检拒绝（expected enum ['periodic','milestone','anomaly','manual']）。"
root_cause: "工具描述中只写了\"主动触发\"等语义说明，未列出 trigger 的枚举取值（periodic/milestone/anomaly/manual），模型按习惯传入自由文本描述，被参数预检拦截。同类风险存在于所有含枚举/格式约束的参数。"
solution: 失败后立即从预检回执中提取准确的枚举约束，选用语义最贴合的合法值（本例 trigger='periodic'）重试一次即成功。通用模式：① 工具首次调用失败且为参数类错误时，优先把回执中的 expected/got 信息当作权威 Schema 补充，按其更正后重试一次；② 事前预防：对不熟悉/描述未列全约束的工具，首次使用前先用 get_tool_schema 获取完整定义（含枚举），把 Schema 检查前置到调用前，避免消耗一轮失败。
evidence: "本轮两次 self_evaluate 调用回执（第 1 次 [状态: failure] 参数预检失败；第 2 次 [状态: success] 落盘 SE-20260903-001-4d91）；eval:SE-20260903-001-4d91（tool_efficiency 0.50，样本 2，其中 1 次失败即本次枚举失配）"
tags: [tool-usage, param-schema, enum-constraint, retry-pattern, get_tool_schema]
source: {}
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-03T18:52:12.096391+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "rule:RULE-AI-02"
promoted_to_rule: RULE-AI-02
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

复用条件：任何工具首次调用失败且错误为参数预检（enum/格式/必填缺失）类时。禁止行为：同参数盲重试、凭训练数据猜测参数格式。关联指标：SE-20260903-001-4d91 tool_efficiency=0.50。