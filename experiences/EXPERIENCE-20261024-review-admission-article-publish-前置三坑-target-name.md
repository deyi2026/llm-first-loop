---
title: review_admission article_publish 前置三坑：target_name=页面按钮名、preview 后才 start、先 browser_perceive 换绑
scenario: 头条发布链路（_dXXc_full.py + review_admission article_publish 双闸），多 tab CDP 环境
root_cause: ""
solution: "发布脚本链路固定为 open→state→prepare→title→ai→verify→preview→browser_perceive(target_id=发布页)→review_admission start→status PASS→admission 回执→confirm；target_name 固定「确认发布」。当前性验证：新班次发布前 grep -n 'admission.json' docs/promotion/_d3Xc_full.py 确认 confirm 阶段仍校验 admission PASS；review_admission 回执 target 字段仍为 \"article_publish:确认发布\"。"
evidence: "2026-10-24 daily-35 发布实测：两次 target_name 描述性名称均拒（publication_target_name_required）；改「确认发布」后 MultiPageAmbiguityError（9 page）；open+browser_perceive 换绑 537FF29F 后 preview 前仍拒（publication_button_not_observed）；preview 出 CONFIRM_BTNS(921,728) 后 start 成功 → status PASS（candidate_sha256 983447e5…）→ confirm 发布成功。d34 回执 daily34-admission.json 佐证 target=\"article_publish:确认发布\"。"
tags: [review_admission, article_publish, toutiao-publish, cdp, gate-order]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-24T14:11:24.236666+08:00"
updated_at: "2026-10-24T14:11:24.236666+08:00"
supersedes: [EXPERIENCE-20261021-article-publish-闸门-target-name-页面真实发布目标-先注入后开闸]
---

review_admission kind=article_publish 三步前置，缺一即确定性失败：(1) target_name 必须填页面目标名「确认发布」（填描述性名称如「daily-35-toutiao-publish」会被拒 publication_target_name_required）；(2) 「确认发布」按钮只在点击「预览并发布」后才出现，admission start 必须排在发布链路 preview 阶段之后（否则 publication_button_not_observed）；(3) CDP 多 page 时直接 start 报 MultiPageAmbiguityError，须先 browser_perceive(target_id=发布页) 换绑。正确顺序：open → prepare/title/ai/verify → preview（出现确认发布浮层）→ browser_perceive 换绑 → review_admission start → status 轮询 PASS → 写 admission 回执（frozen_md_sha 等）→ confirm。当前性验证：grep -n '确认发布' docs/promotion/_d35c_full.py 应命中 confirm 阶段按钮定位行；cat docs/promotion/receipts/daily35-admission.json 应见 target="article_publish:确认发布" 与 qualification=PASS。