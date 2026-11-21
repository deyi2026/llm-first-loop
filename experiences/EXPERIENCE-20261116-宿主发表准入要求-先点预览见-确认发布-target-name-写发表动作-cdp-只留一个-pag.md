---
title: 宿主发表准入要求：先点预览见「确认发布」+ target_name 写发表动作 + CDP 只留一个 page
scenario: "d90 早班头条发布链路：review_admission(action=start, kind=article_publish) 首次调用返回 MultiPageAmbiguityError（observed=5：本次发布页 + d89 文章页×2 + d88 文章页 + 头条号内容管理页）；target_name 传成「article_publish:确认发布」时又返回 publication_target_name_required；改为先点预览让宿主观察到「确认发布」按钮、target_name 传「确认发布」、并关闭多余 page 只留目标页后准入通过。"
root_cause: 宿主 review_admission 在 article_publish 模式下要求：(a) CDP endpoint 恰好暴露一个 page（多页 → MultiPageAmbiguityError，不做 fuzzy 绑定）；(b) target_name 必须是发表动作目标（文章标题会被判 publication_target_name_required）；(c) 页面上必须能观察到「确认发布」按钮。三者任一不满足即确定性拒绝。
solution: "步骤序：(1) 先在编辑器里完成粘贴/标题/AI 声明/自检，再点「预览并发布」，等浮层里出现「确认发布」按钮并记录其坐标；(2) 用 CDP /json/close/<id> 关掉其余 page（只保留目标发布页），确认 /json/list 里 type==page 的条目只剩 1 个；(3) review_admission(action=start, kind=article_publish, target_name='确认发布', manuscript_path=主稿绝对路径, artifact_paths=配图绝对路径列表, scope='tree')；(4) 轮询 review_admission(action=status, child_id, wait_seconds=30) 直到 qualification=PASS；(5) 落盘准入回执（受保护字样字段用 edit_file 写入），再执行发布脚本的 confirm 阶段。artifact_paths 不要放大的 HTML（会被判 review_material_file_too_large），正文用 manuscript_path 绑定 SHA。"
evidence: "本班实测回执：start 第一次 MultiPageAmbiguityError（observed=5，pages 列表含 D5B50E3E…/2072B5B8…/F9211127…/049822398F…/15064F279…）；target_name='article_publish:确认发布' → publication_target_name_required；target_name='确认发布' + 关闭 4 个 page（复检 /json/list 只剩 D5B50E3E34CD943B6FE12B5C8F275C55）后 start 成功，child=subagent_6cc1869e9077，material_chars=35107，scope=tree；status 回执 qualification=PASS、artifact_reviewed=true。"
tags: [review_admission, article_publish, CDP, 宿主准入, 头条发布, RULE-AI-28]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T08:28:56.705984+08:00"
updated_at: "2026-11-16T08:28:56.705984+08:00"
---