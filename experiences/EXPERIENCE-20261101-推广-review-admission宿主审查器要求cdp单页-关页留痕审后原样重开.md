---
title: 推广-review_admission宿主审查器要求CDP单页-关页留痕审后原样重开
scenario: "推广发布流程中调用宿主 review_admission 做 article_publish 准入审查时，CDP 127.0.0.1:9229 上有 8 个页面（发布页、LFL WebUI、chatgpt、知乎创作者、GitHub 等历史标签），审查器无法绑定，确定性失败。"
root_cause: ""
solution: "按\"先预览后关页\"的顺序操作：preview 阶段先点出「确认发布」浮层（否则受理被拒 publication_button_not_observed），再把待关页面 URL 全量落盘留痕，关闭除发布页外全部标签，重试 review_admission 受理成功；审查 PASS、confirm 发布完成后，按留痕把用户页面原样重开（自动化产物页不重开）。"
evidence: "docs/promotion/receipts/daily50-tabs-closed.json（7 页留痕+reopen 标记）；docs/promotion/receipts/daily50-admission.json（PASS，child subagent_b9d5a0dc4f96）；src/llm_loop/browser/errors.py:28-45 与 cdp_host.py:405-410（单页约束实现）；docs/promotion/STATUS-20261101-daily50.md 第六节"
tags: [推广发布, review_admission, RULE-AI-28, CDP, 浏览器标签管理]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T13:42:00.638852+08:00"
updated_at: "2026-11-01T13:42:00.638852+08:00"
---

宿主 review_admission（RULE-AI-28）的浏览器审查器绑定 CDP 页面时要求"恰好一个 page"，多页即确定性失败 MultiPageAmbiguityError（携带只读页面清单；无 target_id 参数可传，cdp_host.py:409 len(pages)!=1 即 raise）。处置流程（2026-11-01 d50 实测有效）：①先完成 open/prepare/title/ai/verify/pageman/preview（预览浮层「确认发布」按钮必须已出现，否则受理报 publication_button_not_observed）；②把全部页面清单连同 URL 写入回执（如 receipts/daily50-tabs-closed.json）留痕；③仅保留发布页，逐个 close 其余标签（PUT /json/close/{id}）——标签关闭可逆（URL 可原样重开），自动化产物页（如 hot-board）标记不重开；④review_admission start→status 拿 PASS；⑤confirm 之后按留痕把 reopen=true 的用户页面逐个原样重开（/json/new?URL）。注意：关闭的是"页面"不是登录态，cookies 不受影响；不确定归属的用户页面关闭前先记录 URL，宁可重开恢复也不丢留痕。