---
title: self_evaluate 的 trigger 必须使用受控枚举值
scenario: 里程碑节点后需要提交自我评估验证时，调用 self_evaluate 做手动评估。
root_cause: 向 trigger 传入自然语言描述，触发参数校验失败；该字段只接受 periodic/milestone/anomaly/manual 四类受控值。
solution: "用户主动要求或架构上报建议评估时，直接使用 trigger='manual'；周期汇总用 periodic，里程碑用 milestone，异常排查用 anomaly。评估完成后如需改进，用返回的 eval:<评估ID> 作为 evidence submit_evolution。"
evidence: "本轮首次 self_evaluate(trigger='用户要求提交验证；...') 返回 [状态: failure] 参数错误；更正为 trigger='manual' 后成功生成 SE-20260816-002-bad2。"
tags: [self_evaluate, 参数约束, 受控枚举, 效率]
source:
  eval_id: SE-20260816-002-bad2
  origin: user_request_submit_validation
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-08-16T13:41:36.017917+08:00"
updated_at: "2026-09-11T19:34:33.266797+08:00"
superseded_by: "rule:RULE-AI-02"
promoted_to_rule: RULE-AI-02
last_verified_at: "2026-09-11T19:34:33.266797+08:00"
---