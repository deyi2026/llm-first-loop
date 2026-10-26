---
title: review_admission 对真实头条发布页结构性超限（_BROWSER_PAGE_MAX_BYTES=78000），该路径不可靠
scenario: "为头条文章做 review_admission（目标名\"确认发布\"）时，页面是已填满 2634 字正文 + 6 张图的 mp.toutiao.com 编辑页。实测审查材料远大于准入上限，start 被结构性拒绝，与稿件质量无关。"
root_cause: ""
solution: "真实浏览器发布页普遍超限：当前源码 src/llm_loop/tools/review_host_admission.py 有 _BROWSER_PAGE_MAX_BYTES = 78_000，浏览器投影超过即 raise browser_page_review_cap_exceeded（头条实测 outerHTML 约 94 万字符、语义投影 token_estimate 约 26 万，必然超限）。不要靠重试解决。可行收口：审查在页面填充前对稿件 md + 图片文件做（本次即 PASS 且 SHA 绑定），发布动作走 CDP 脚本路径绕开 P0-B 的浏览器入口判定——但该路径的授权依据必须如实落盘，不得默认视为已授权。当前性验证：grep -n \"_BROWSER_PAGE_MAX_BYTES\|browser_page_review_cap_exceeded\|browser_page_review_too_large\" src/llm_loop/tools/review_host_admission.py 确认上限值与错误码名称仍存在（本次实测上限 78_000、错误码已由 browser_page_review_too_large 改名为 browser_page_review_cap_exceeded，说明该处正在演化，旧回执里的行号/错误码不可直接复用）。"
evidence: "本次实测：grep -n \"_BROWSER_PAGE_MAX_BYTES\|browser_page_review_cap_exceeded\" src/llm_loop/tools/review_host_admission.py → 551:_BROWSER_PAGE_MAX_BYTES = 78_000；699:if size > _BROWSER_PAGE_MAX_BYTES；700:raise ValueError(f\"browser_page_review_cap_exceeded:{size}>{...}\")。浏览器侧：src/llm_loop/browser/action.py:721-732 review_authorizer 返回 allowed=False 时走 _append_rejected(...,\"review_admission_blocked:\"+reason)。页面侧实测 outerHTML 939158 字符、token_estimate 262907（receipts/20261018-daily18-publish.json host_admission 段）。"
tags: [review_admission, P0-B, 头条, RULE-AI-28, 准入上限]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T20:26:42.119935+08:00"
updated_at: "2026-10-18T20:26:42.119935+08:00"
---