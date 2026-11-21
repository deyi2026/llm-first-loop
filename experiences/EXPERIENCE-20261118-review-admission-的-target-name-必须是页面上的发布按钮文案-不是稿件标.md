---
title: review_admission 的 target_name 必须是页面上的发布按钮文案，不是稿件标题
scenario: "头条/其它平台自动发表前调用 review_admission(action=start, kind=article_publish) 时，把 target_name 写成文章标题或稿件文件名，宿主直接拒绝受理并返回 reason=publication_target_name_required；另一次把 artifact_paths 里的配图文件名写错（实际名与臆造名不一致），返回 reason=review_material_not_a_file。"
root_cause: ""
solution: target_name 填页面预览抽屉里真实可见的发布按钮文案（头条是「确认发布」），且必须先点开预览让宿主能观察到该按钮；artifact_paths 必须是磁盘上真实存在的文件名（发布前先 ls/搜索确认图名，不要按语义臆造）。宿主受理后 status 返回 qualification=PASS，再把 PASS 落成 receipts/<期>-admission.json（frozen_md_sha 必须等于当前主稿 sha），脚本的 confirm 阶段才有资格点发布。
evidence: "evidence://v1/03d785249f2f0521807866fd3445e29c8cc002076acdac31e96141363aa0a5ed（start 受理，candidate_sha256=fd8eb4b0…，reviewer=glm/glm-5.3-flash，status qualification=PASS）；evidence://v1/86f66cb0153ebdbe0c1f72370a6b771789bcb32b8c8a4581f44db8be6e44abd88cd（start 受理）；evidence://v1/9d7850c7c48ee5ecbf8fc7d8e6a4a56a4a97b1d5cd0a5b6ea1e51cd0e94a1e6a5（publication_target_name_required / review_material_not_a_file 两次被拒回执）"
tags: [review_admission, rule-ai-28, 发表准入, 头条发布, 参数语义]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-18T11:00:45.945314+08:00"
updated_at: "2026-11-18T11:00:45.945314+08:00"
---