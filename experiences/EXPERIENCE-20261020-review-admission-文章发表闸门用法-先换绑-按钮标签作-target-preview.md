---
title: review_admission 文章发表闸门用法：先换绑、按钮标签作 target、preview 后 confirm 前
scenario: 发表前需要用 RULE-AI-28 Host 闸门 review_admission(kind=article_publish) 对已填稿的浏览器发布页取得独立审稿 PASS 资格，再执行不可逆的发布点击。
root_cause: ""
solution: 先换绑（browser_perceive+target_id）→ 填稿+preview 打开确认层 → review_admission start（target_name=按钮标签）→ 轮询 status 至 PASS → 写资格文件（含 frozen SHA 清单）→ confirm 前校验文件 SHA 无漂移。
evidence: "receipts/20261020-daily23-admission.json（qualification=PASS, child_id=subagent_e613015b40ac）与本会话 review_admission 两次失败回执（publication_target_name_required、MultiPageAmbiguityError）及成功回执"
tags: [review_admission, rule-ai-28, article_publish, cdp, gate]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T13:42:59.572922+08:00"
updated_at: "2026-10-20T13:42:59.572922+08:00"
supersedes: [EXPERIENCE-20261018-review-admission-的送审稿必须按页面可见正文的行结构落盘-并排除图片块-ui-文字与, EXPERIENCE-20261019-review-admission-发表闸-资格与-grounding-ref-都绑定页面世界版本]
---

review_admission 对 article_publish 的三步前置：①CDP 多页面时报 MultiPageAmbiguityError——须先 browser_perceive(action=snapshot, target_id=&lt;发布页 page_id&gt;) 显式换绑 host（该调用本身是独立 rebind 动作，观察/后续 capture 走绑定页）；②target_name 不是平台名或文章名，须匹配发布按钮标签正则（publish/post/发表/发布/立即发布/确认发布 等），页面里必须实际存在该按钮——所以要先 preview 打开确认对话框让「确认发布」可观察；③闸门时点在编辑器填稿完成后、confirm 前（Host 绑定 manuscript 文件 SHA+页面可见正文）。回执 candidate_sha256 是 Host 绑定摘要（页面正文+指纹），不等于 MD 文件 SHA，下游脚本校验应分别用 frozen 清单与 candidate 字段。本日全流程通过：start→pending→PASS→confirm 单次点击→已发布。