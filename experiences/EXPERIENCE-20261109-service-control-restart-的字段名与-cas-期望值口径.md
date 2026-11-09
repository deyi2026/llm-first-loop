---
title: service_control restart 的字段名与 CAS 期望值口径
scenario: 通过 service_control 对 feishu/wecom/learning 发单独物理 restart（web 已收敛不动）
root_cause: ""
solution: restart 契约：必填字段是 target（enum web/feishu/wecom/learning/all），不是 schema 描述里出现的 restart_target；expected_generation 的 CAS 基准是 status 顶层 deployment.generation（部署代），不是各服务行内 verify.generation。冲突回执会给 current，按回执重试即可
evidence: "失败回执×2（missing=target；expected=400 current=402）+ 成功回执 action_id=svc-d4acd1dc649f43528f50b0d03a6fb0f8(feishu, pid 4456)/svc-65f880cc0cca47039b0bb2ed825b8da6(learning, pid 5337)/svc-86d3757c12024406a751ae94f04d6a2e(wecom, pid 4798)，2026-11-09 16:36-16:39 本会话 service_control 回执链；契约单测 tests/unit/test_service_control_argument_contract.py:57（search_files 命中）"
tags: [service_control, restart, cas, 参数契约]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T16:41:38.399793+08:00"
updated_at: "2026-11-09T16:41:38.399793+08:00"
---

现象1：action=restart 带 restart_target=<svc> 被拒：「missing=target; required=target」。现象2：expected_generation 取 status 里服务行 verify.generation=400 被拒：「deployment generation changed: expected=400 current=402」。修正：字段用 target；CAS 期望值取 status 顶层 deployment.generation（本例 402）。三个 restart 修正后一次受理成功，终态均 succeeded。当前性验证：grep -n "required=target" tests/unit/test_service_control_argument_contract.py 仍命中（HEAD 25cc00cd2 为 :57）；或 pytest tests/unit/test_service_control_argument_contract.py -q 全绿即契约仍如此。