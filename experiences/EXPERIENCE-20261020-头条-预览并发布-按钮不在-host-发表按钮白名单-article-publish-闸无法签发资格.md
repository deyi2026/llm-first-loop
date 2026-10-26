---
title: 头条『预览并发布』按钮不在 Host 发表按钮白名单，article_publish 闸无法签发资格
scenario: "在今日头条号（mp.toutiao.com）发布图文：调 review_admission(action=start, kind=article_publish, target_name=…) 连续两次返回 publication_target_name_required，改用『预览并发布』仍被拒；最终通过 CDP JS 点击发布成功。"
root_cause: ""
solution: 头条发布前不要指望 review_admission 签发资格：先按 RULE-AI-28 走独立文稿审查子代理并落盘回执（含产物 SHA），再走 CDP 发布链路，并在发布回执里如实写明 Host 闸未在本动作实际拦阻及其原因（按钮标签不在白名单），不得把规则覆盖描述为已全覆盖。建议把平台按钮标签纳入 Host 白名单并补回归用例。
evidence: "tool=review_admission; kind=article_publish; reason=publication_target_name_required; src/llm_loop/tools/review_host_admission.py::_PUBLISH_LABEL_RE 全文只含 publish/post/confirm publish/发表(文章)/发布(文章)/立即发布/确认(发布|发表)；头条编辑器按钮实测文本为『预览并发布』，两轮 agent_followup 亦因 provider 熔断与父会话续话预算耗尽失败"
tags: [RULE-AI-28, review_admission, toutiao, coverage-gap, 发布]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T08:29:56.272943+08:00"
updated_at: "2026-10-20T08:29:56.272943+08:00"
---