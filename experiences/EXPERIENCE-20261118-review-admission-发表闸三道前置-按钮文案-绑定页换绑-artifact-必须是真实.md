---
title: review_admission 发表闸三道前置：按钮文案、绑定页换绑、artifact 必须是真实文件
scenario: 头条图文发布链路里，对已填满正文与配图的真实 mp.toutiao.com 编辑页调用 review_admission(kind=article_publish) 启动 RULE-AI-28 宿主审稿闸。
root_cause: ""
solution: 顺序：先在编辑页打开预览使「确认发布」按钮出现 → browser_perceive 带 target_id 把宿主绑定页换绑到该编辑页 → 用 md2html.py 另生成纯 HTML 并与主稿、台账、配图一起列入 artifact_paths（全部为真实文件）→ target_name 填「确认发布」→ start → status 轮询到 qualification=PASS。
evidence: "docs/promotion/STATUS-20261118-daily97.md 第三节与第九节；三次 start 的失败回执 reason 依次为 publication_target_name_required、publication_button_not_observed、review_material_not_a_file:20261118-lfl-daily-97.html；第 4 次 start accepted（child_id=subagent_06879a201beb, reviewer glm/glm-5.3-flash, scope=tree, candidate_sha256=c85539fa…），status 回执 qualification=PASS 且 artifact_reviewed=true。"
tags: [review_admission, 规则AI-28, 头条推广, artifact_paths, browser_perceive, 发表闸]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-18T13:47:17.763590+08:00"
updated_at: "2026-11-18T13:47:17.763590+08:00"
---

场景：对已填好的头条发布页做 review_admission(kind=article_publish)。本班连续 3 次被拒，三次原因互不相同且都是前置条件、不是稿件质量问题：
① reason=publication_target_name_required —— target_name 不能写稿件标题，必须是页面上真实存在的发布按钮文案（头条为「确认发布」）。
② reason=publication_button_not_observed —— 宿主用自己的绑定页观测按钮。本班编辑页在 CDP 9229 的另一个 target 上，宿主绑定页当时停在作品管理页，于是按钮观测不到。解法：先 browser_perceive(action=snapshot, target_id=<编辑页 target id>) 把宿主绑定页换绑到编辑页，再 start。
③ reason=review_material_not_a_file:<name> —— artifact_paths 里每一项都必须是磁盘上真实存在的文件。发布链路里 build 脚本只产出 receipts/dxx-paste.html（含 data-URI 内嵌图，体量大且不适合当审查材料），审稿要的纯 HTML 要另外用 md2html.py 直接转换生成一个 .html 再列入。
适用范围：任何"文稿/代码发表前独立审查闸"的准入环节。