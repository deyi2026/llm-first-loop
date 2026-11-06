---
title: "宿主 article_publish 审查材料 78,000 字节硬上限：先砍主稿字数，再减附件件数，页面固定开销无解"
scenario: "LFL 每日推广班次在今日头条发布前走宿主 RULE-AI-28 article_publish 准入；长文稿（正文约 13,000 汉字 + 5 张图 + 参考来源 + 尾注）反复触发 browser_page_review_cap_exceeded:81482>78000 / 78886>78000。"
root_cause: ""
solution: "读宿主源码确认 78,000 字节上限的材料构成后，按「先砍主稿字数 → 再减附件件数」的顺序削减，并在每轮改稿后重跑台账审计与 HTML 构建校验；页面固定开销不动。"
evidence: "docs/promotion/receipts/d66-build.json（md_sha256/html_sha256）；三次 review_admission start 回执 browser_page_review_cap_exceeded:81482>78000 / 78886>78000 / accepted(material_chars=36237)；.releases/6d69360e812dc65ec8a6759a0a232b73ffdf78ab/src/llm_loop/tools/review_host_admission.py:2134(_BROWSER_PAGE_MAX_BYTES=78_000)、2146(_BROWSER_TEXT_SEND_CHARS=20_000)、3049-3061(降级与拒绝逻辑)"
tags: [promotion, toutiao, review_admission, byte-cap, publish-chain]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T20:56:29.372053+08:00"
updated_at: "2026-11-06T20:56:29.372053+08:00"
---

教训=重做会避免一次已发生失败的运作规则。
宿主 RULE-AI-28 的 article_publish 审查材料有 78,000 字节硬上限（browser_page_review_cap_exceeded）。材料构成（读源码 review_host_admission.py 确认）：页面可见文本（节点文本属性去重后按 20,000 字符截断，约 52KB）+ 主稿全文 + 每个附件的文件指纹（每件约 195 字节）+ 少量结构开销。超限时页面部分会被降级截断一次，若仍超限就直接拒绝。
削减优先级：① 先砍主稿字数（唯一能同时降主稿与页面文本两项的杠杆，正文每删 1 汉字约减 2.3 字节主稿）；② 再减附件件数；③ 压缩页面固定开销无有效手段（页面 chrome 与正文无关，且预览浮层必须开着才有「确认发布」按钮）。
纪律：压缩只删冗余表述，不删事实、数值与限定语；每次改稿后必须重跑 R5 台账审计（AUDIT PASS）与 md2html 构建校验（BUILD PASS），否则正文与台账会脱节。
本班实际代价：d66 晚班稿为满足该上限连续做 8 轮压缩（26,042 → 24,474 字节），其中 6 轮是被审稿抓出的口径走样（详见同任务 companion lesson）。