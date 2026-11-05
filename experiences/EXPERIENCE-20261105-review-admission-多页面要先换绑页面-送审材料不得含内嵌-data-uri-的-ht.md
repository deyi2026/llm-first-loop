---
title: review_admission 多页面要先换绑页面、送审材料不得含内嵌 data-URI 的 HTML 与大图
scenario: "LFL 推广班次发布前走 review_admission(kind=article_publish, target_name=确认发布) 准入闸，浏览器开着 7 个页面（头条号列表页、发布页、Gemini 等）。"
root_cause: ""
solution: |
  1) 多页面时先换绑：调 browser_perceive(action=snapshot, target_id=<发布页 page_id>)——该调用只执行换绑不读取内容，随后 review_admission 不带 target_id 即可命中唯一页面；否则报 MultiPageAmbiguityError(observed=N)。
  2) 送审材料瘦身：发布用 HTML 因内嵌 4 张 data-URI 图可达 1MB，与 PNG 图一起送审会报 review_material_file_too_large。只送「稿件 md + 台账 + 修订对照表」三样（约 35KB）即可受理；送审正文稿必须是页面可见正文行结构（pageman 落盘），不是 md 源稿。
  当前性验证：跑 review_admission(action=start, kind=article_publish, target_name=确认发布)，回执应出现 accepted=true 与 material_chars 约 4 万；若报 MultiPageAmbiguityError 说明未换绑，若报 review_material_file_too_large 说明送审材料仍含内嵌图 HTML/PNG。
evidence: "2026-11-05 d61 早班实测：首次 start 报 MultiPageAmbiguityError: observed=7；换绑后报 review_material_file_too_large；去掉 HTML 与 PNG、只送 md+台账+对照表后受理并 PASS（child subagent_c01a0e6e1b7f, material_chars=40657）。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-05T08:52:43.224128+08:00"
updated_at: "2026-11-05T08:52:43.224128+08:00"
supersedes: [EXPERIENCE-20261024-review-admission-article-publish-前置三坑-target-name, EXPERIENCE-20261103-审稿意见给的-推断-vs-原文-判断必须自己回源核对-review-admission-需先清掉浏览]
---