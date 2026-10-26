---
title: review_admission article_publish：target_name 必须精确等于页面发布按钮标签（如「确认发布」），且 Host capture 须先换绑到含该按钮的页面
scenario: 头条/知乎等平台文章发布前走 RULE-AI-28 review_admission 闸门：先用自由文本 target_name（如「今日头条 mp.toutiao.com 图文（LFL 推广第 28 期 daily28）」）两次被拒 publication_target_name_required；改成页面按钮标签「确认发布」后又遇 publication_button_not_observed（Host capture 绑定页不含该按钮）。d25 STATUS 曾记录 publication_button_not_observed 的视觉定位解法，但 target_name 的合法值域这次才踩实。
root_cause: ""
solution: target_name 一律传当前页面可见的发布确认按钮精确文本（中文平台即「确认发布」）；调用时机放在「预览并发布」点开、确认浮层已渲染之后；调用前先 browser_perceive 显式 target_id 换绑到该浮层所在 tab。
evidence: "src/llm_loop/tools/review_host_admission.py:53-60（_PUBLISH_LABEL_RE）、1099-1113（target_name 校验与 capture 检查）；docs/promotion/STATUS-20261022-daily28.md D28-G；receipts/daily28-admission.json"
tags: []
source: {}
status: archived
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T08:39:18.985569+08:00"
updated_at: "2026-10-22T08:40:02.437661+08:00"
supersedes: [EXPERIENCE-20261020-review-admission-文章闸-送审稿须按页面渲染态生成-删粗体内容-120字符折行]
---

review_admission(kind=article_publish) 的 target_name 不是自由文本描述，必须精确匹配 src/llm_loop/tools/review_host_admission.py 的 _PUBLISH_LABEL_RE（r"^(?:publish(?:\s+(?:now|post|article))?|post(?:\s+(?:now|article))?|confirm\s+publish|发表(?:文章)?|发布(?:文章)?|立即发布|确认(?:发布|发表))$"）——中文场景实际可用值即页面发布按钮标签「确认发布」。不匹配报 publication_target_name_required（与 target_name 是否非空无关）。第二个前置：Host browser_capture 绑定的页面必须含该按钮（is_publication_button 语义对象），否则报 publication_button_not_observed；发布浮层出现后先 browser_perceive(target_id=发布页) 显式换绑再调闸门（EXPERIENCE-20261020 的适用场景正是此处）。manuscript_path/artifact_paths 用绝对路径最稳。2026-10-22 d28 实测：自由文本两次拒绝、换绑前一次拒绝、换绑后第 3 次受理一次 PASS（child=subagent_431b5d72b49c）。