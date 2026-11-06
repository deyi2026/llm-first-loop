---
title: review_admission 宿主绑定页可能已失效：先换绑再启动，且准入应在预览浮层「确认发布」出现之后启动
scenario: "LFL 推广班次调 review_admission(action=start, kind=article_publish) 两次直接报错「bound Browser target disappeared: 156689D6…; no silent rebind」——宿主绑定的 target 是上一班遗留、已关闭的标签页。同时顺序也不对：第一次 start 时页面还没点「预览并发布」，浮层里并不存在「确认发布」按钮。"
root_cause: ""
solution: "先跑发布脚本的 open→clear→prepare→title→ai→verify→preview，让浮层「确认发布」出现；再用 browser_perceive(action=pages) 看当前绑定页是否仍存在，若绑定页已消失则用 browser_perceive(action=snapshot, target_id=当前发布页 target_id) 换绑，然后再启动 review_admission。宿主 status 回执只返回 qualification/candidate_sha256/artifact_reviewed/scope，不返回 frozen_md_sha——该字段需由本班对送审稿路径自行计算，并在回执文件里注明与宿主 candidate_sha256 的口径差异。"
evidence: 本班两次 start 报错原文；browser_perceive(pages) 显示 binding_page_id=156689D6… 与 8 个现存 page；换绑后 start 成功（child subagent_bcbb26dd60d2，qualification=PASS）；receipts/daily64-admission.json
tags: [规则28, review_admission, 换绑, 发布链路]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T08:33:20.877459+08:00"
updated_at: "2026-11-06T08:33:20.877459+08:00"
supersedes: [EXPERIENCE-20261105-review-admission-多页面要先换绑页面-送审材料不得含内嵌-data-uri-的-ht]
---