---
title: 宿主准入 review material 的 78KB 上限：页面文本被截断，只有主稿与 artifact 指纹能压
scenario: "今日头条文章发布走 review_admission(kind=article_publish) 时，反复报 browser_page_review_cap_exceeded:79xxx>78000；正文 35KB 左右的中文长稿（d82）过不去，而同样流程昨天 25KB 的 d81 通过。"
root_cause: ""
solution: "material 的字节构成：页面可见文本（按 20,000 字符截断，截断后对压缩不再敏感）+ 主稿正文（1 字节正文 = 1 字节 material，线性）+ artifact 指纹（每个约 200 字节）。因此压体积只能压主稿本身与 artifact 数量；压主稿时优先找「与正文重复的整段」（本班删掉参考来源末尾与 §八 重复的 LFL 逐符号明细块，保留 §八 的聚合读数），不要删英文原句摘录。artifact_paths 传 0 个时 material 仍超限，所以「少传 artifact」不是主要杠杆。"
evidence: "evidence://v1/c7e52656bc20bd8a3d48978c7b5e83de732ea84457bde6f0e2462e9a55649ec7（accepted, material_chars=43925）；evidence://v1/57d0a0dd671a66a56a08db4634e0092cad408327e13e708596913d4ccc72e322（accepted, 43,915）；三次拒绝回执 79,346/78,946/79,121（source=review_admission）"
tags: [review_admission, article_publish, material_cap, promotion, size_budget]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T09:47:43.870631+08:00"
updated_at: "2026-11-13T09:47:43.870631+08:00"
---

复现与当前性验证：
- 当前性验证：grep -n '_BROWSER_TEXT_SEND_CHARS\|browser_page_review_cap_exceeded' src/llm_loop/tools/review_host_admission.py 确认 20,000 字符截断常量与上限报错码仍在同文件。
- 复现：同一篇稿，review_admission(start, manuscript_path=md, artifact_paths=[6 项]) 的 material 字节数 ≈ 44KB(非正文部分) + 正文字节数；正文每多 1KB，material 多约 1KB。
- 本班实测：拒绝 79,346 / 78,946 / 79,121 三次；压缩到正文 32,488 字节后 accepted（material_chars 43,925）。