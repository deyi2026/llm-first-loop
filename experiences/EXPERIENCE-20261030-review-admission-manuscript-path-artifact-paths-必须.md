---
title: review_admission manuscript_path/artifact_paths 必须传绝对路径：相对路径被 basename 化报 not_a_file
scenario: "LFL 头条发布链路（Rule28 article_publish 双闸）调用 review_admission(action=start) 时，workdir=docs/promotion，manuscript_path 传 \"receipts/daily43-manuscript-page.txt\"（相对 workdir），artifact_paths 传 \"img/fig181-xxx.png\" 等相对路径；文件实际存在。"
root_cause: ""
solution: "两类路径都传绝对路径：manuscript_path=/Users/.../docs/promotion/receipts/xxx.txt、artifact_paths=[/Users/.../docs/promotion/img/xxx.png,...]。判定依据是报错形态：reason=review_material_not_a_file:<basename>（路径只剩文件名，说明相对前缀被剥离后到 workdir 下找，必然失败）。本班三次调用回执链实证：①相对 manuscript → not_a_file:daily43-manuscript-page.txt；②绝对 manuscript + 相对 artifacts → not_a_file:fig181-workflow-bypass.png；③全绝对 → accepted 一次过。"
evidence: "本会话三次 review_admission 调用回执：failure{reason:review_material_not_a_file:daily43-manuscript-page.txt} → failure{reason:review_material_not_a_file:fig181-workflow-bypass.png} → success{accepted:true, candidate_sha256:c74f9f60...}；文件 receipts/daily43-manuscript-page.txt 与 img/fig181-*.png 实存（pageman 阶段产出/read_image 消费过）。"
tags: [review_admission, rule28, article_publish, 绝对路径, 发布链路]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T08:39:48.267266+08:00"
updated_at: "2026-10-30T08:39:48.267266+08:00"
---

当前性验证：重跑 review_admission(action=start, kind=article_publish, workdir=<dir>, manuscript_path=<相对路径>) 应复现 reason=review_material_not_a_file:<basename>（路径前缀被剥离）；换绝对路径重试应 accepted:true。若相对路径也能 accepted，说明路径解析已修复，本卡可失效。