---
title: spawn_subagent 模型名须带 provider 前缀；被栅栏的审查子代理不能跑测试时由父会话补跑
scenario: RULE-AI-28 代码闸：spawn 审查子代理做独立代码审查（glm-5.3）
root_cause: ""
solution: spawn 时用 glm/glm-5.3 完全限定名；审查子代理回执若显示 shell 被 fenced，由父会话复跑测试并如实标注测试证据来源。
evidence: "失败回执：evidence://v1/41ef22b90a66f27131c8473e5bb1ca49f8a36cdca3c0a845f2b104baa27499c7（裸名 refused）；成功回执：evidence://v1/52629ee56993aa1a7065f883e89c775cd5e860748beea250e805255e69167255（glm/glm-5.3 spawn 成功）；审查输出（shell fenced、44 调用）：evidence://v1/7e9c889723ff62a21f71d2094d7e7727674cd30781bac6ca973ca590af247365；父会话补跑测试回执：evidence://v1/15cc84f579c47f05338ca2e7f0d49e490e5f3dc65bd64c9b548bc17b59c79383（20/20）。时间：2026-10-14。"
tags: [spawn_subagent, model-naming, RULE-AI-28, 代码闸, glm-5.3]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T16:39:25.418816+08:00"
updated_at: "2026-10-14T16:39:25.418816+08:00"
---

事实1：spawn_subagent 的 model 参数传裸名 "glm-5.3" 会因多 provider 匹配（glm/glm-5.3、workbuddy/glm-5.3）确定性失败（child_state=refused, child_model_unavailable）；必须用带 provider 前缀的完全限定名（model_catalog 回执格式 provider/model）。用户偏好：子代理默认用 glm/glm-5.3。事实2：RULE-AI-28 代码闸的审查子代理在租约栅栏下 execute_command 会被拒（"effect authority 丢失 run lease fenced"），其静态读码审查仍有效，但"独立运行测试"环节不可达——测试必须由父会话复跑并以父会话回执为准；呈报时如实标注这一分工，不得把子代理"测试未跑"包装成"测试通过"。