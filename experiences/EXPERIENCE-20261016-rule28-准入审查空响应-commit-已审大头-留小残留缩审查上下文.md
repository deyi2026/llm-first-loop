---
title: Rule28 准入审查空响应：commit 已审大头、留小残留缩审查上下文
scenario: GOAL-20261015-ac085ab1 收口：Rule28 review_admission(full_test) 的审查子会话连续两次死于 LLMEmptyResponseError（glm-5.3 空响应），status 返回 review_has_no_live_host_attestation；当时冻结材料约 75KB 未提交 delta，且同窗口存在 Connection refused 网络抖动。
root_cause: ""
solution: "两步处置：先确认非协议误用（查 child 真实终态 subagent_result + architecture_status exception_log 定位空响应根因）；再采纳用户\"上下文太长做成文件让它读\"的假设——Host 不接受附加文件，等效杠杆是把已有 PASS 回执覆盖的大头先本地 commit（本地提交不触发三闸），仅留真正未审的小残留（2.3KB 登记 JSON）作为新准入材料。r5 审查一次通过。"
evidence: 异常日志（architecture_status exception_log：连续 2 次 review_has_no_live_host_attestation + LLMNetworkError）；subagent_result(subagent_65444243e6fc) 显示 LLMEmptyResponseError 已投递思考 67822 字符无输出；缩材料后 r5 一次 PASS（candidate=3dd5134a），随后全量门 exit=0。单例证据，与 provider 时间窗恢复存在混杂，未做对照实验。
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-16T00:09:24.686867+08:00"
updated_at: "2026-10-16T00:09:24.686867+08:00"
---