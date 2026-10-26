---
title: review_admission reviewer_unavailable 根因：审查材料超 reviewer 子代理 history 预算（非服务故障）与修复链
scenario: review_admission(full_test) 连续 reviewer_unavailable，上会话判为基础设施故障重试 10 次无果
root_cause: ""
solution: subagent_result 取真实失败文本→定位预算公式→改 providers.local.json（优先级链正确源）→refresh_config 热载→重发审核
evidence: "evidence://v1/40b358b9aab7c350a56e3d6db61155fd9627417b0428c4ff5fb98e825368b90 (reviewer 真实失败文本); evidence://v1/5821cf620da8d591c3f9bb81e39e87bb30d630ad594cc2f7dc633fd0ac6603 (providers.json glm max_input_tokens); evidence://v1/724be7ca61c3decd09264f03644086c8065ddbc9cfc0fbd1ec1ea39fbf7ce1d2 (修复后 PASS)"
tags: [review_admission, reviewer_unavailable, providers.local.json, max_input_tokens, 子代理预算, 根因诊断]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T01:15:41.624835+08:00"
updated_at: "2026-10-21T01:15:41.624835+08:00"
---

诊断链（00:16-01:07 实战验证）：
1. reviewer_unavailable 是 _classify_reviewer_failure 的兜底分类，不含真实原因；真实失败文本用 subagent_result(child_id) 直接读（reviewer 子会话 parent 即当前会话）。
2. 本例根因："子代理上下文预检: 模型输入接近实际窗口，但当前子代理没有可调用的 search_archive"——reviewer（review_isolated, required_tools=[]）无归档恢复能力，child wire 字符数 > 预算即 fail closed。
3. 预算公式（runner._bounded_child_wire + factory._child_context_limits）：allowed = min(0.9×context, context−max_tokens, max_input_tokens)；budget_chars = allowed × chars_per_token。glm 原值 184000×0.6≈110,400 字符，而 review_admission 材料上限 192KB → 90KB~192KB 区间材料 start 受理但 reviewer 必死，表现为"连续 N 次 reviewer_unavailable"，极易误判为服务故障。
4. 判别证据：diff 字节数 vs 预算字符数（批次1 54KB 过、批次2 111KB+untracked 34KB 死锁）；batch 对比即定位。
5. 修复：data/providers.local.json（注意优先级链 env JSON > providers.local.json > providers.json，改 providers.json 无效！）glm.max_input_tokens 184000→800000 + refresh_config（registry 原子热载，resolver 读 model_pool.registry 立即生效；默认 client contract 才需要重启）。
6. 附加坑：ci_gate.sh 运行会重写 reports/*.json 时间戳（~323KB 噪声），把审核材料推过 192KB 上限触发 git_state_too_large——review start 前与 commit 前都应 git checkout -- reports/。
7. 门禁产物变更即失效：每次修代码（含守卫基线登记）后全量测试前必须重发 review_admission 覆盖新 SHA。