---
title: review_admission 送审前必须先点预览让宿主观察到「确认发布」按钮，且 target_name 须为发表动作目标而非文章标题
scenario: 文章发表（article_publish）走 review_admission 准入时连续两次被确定性拒绝：①MultiPageAmbiguityError（CDP 多页，observed=9）②关页后仍报 publication_button_not_observed；且首传 target_name=文章标题直接被拒。
root_cause: 宿主 review_admission 的 article_publish 分支要求：(a) CDP 端点唯一页（多页则确定性歧义拒绝，无 fuzzy 绑定）；(b) 目标按钮「确认发布」必须已被宿主观察到存在于页面（即预览浮层已打开）；(c) target_name 是发表动作目标名，不是稿件标题；(d) manuscript 文件正文行数需与页面可见正文一致（传单行 HTML 会被 manuscript_page_text_mismatch 拒）。
solution: "正确顺序：①按 d50/d51 先例关闭除发布页外的所有标签页（留痕）；②先点「预览并发布」使确认发布浮层出现，宿主才能观察到该按钮；③review_admission(action=start, kind=article_publish, target_name='确认发布', workdir=..., manuscript_path=页面可见正文txt)，target_name 必须是发表动作目标「确认发布」而非文章标题；④manuscript_path 传 pageman 页面可见正文 txt，不传 paste.html。"
evidence: docs/promotion/STATUS-20261102-daily52.md 第七节（两次 start 拒绝实录 + 修正后 child subagent_1db09b17ecdd PASS）；回执 docs/promotion/receipts/daily52-admission.json、daily52-tabs-closed.json
tags: [review_admission, article_publish, 头条, 发布链路, CDP]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-02T08:43:52.634237+08:00"
updated_at: "2026-11-02T08:43:52.634237+08:00"
supersedes: [EXPERIENCE-20261101-推广-review-admission宿主审查器要求cdp单页-关页留痕审后原样重开, EXPERIENCE-20261020-review-admission-文章闸-送审稿须按页面渲染态生成-删粗体内容-120字符折行]
---