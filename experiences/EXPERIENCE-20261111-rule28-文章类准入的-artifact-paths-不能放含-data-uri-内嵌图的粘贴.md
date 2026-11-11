---
title: Rule28 文章类准入的 artifact_paths 不能放含 data-URI 内嵌图的粘贴 HTML（会报 review_material_file_too_large）
scenario: Rule28 宿主准入（kind=文章发表）第一次被拒：reason_code=review_material_file_too_large。原因是把含 data-URI 内嵌图（4 张 base64 PNG）的粘贴用 HTML 也放进 artifact_paths，冻结材料体积超限。
root_cause: ""
solution: 文章类准入的 artifact_paths 只放真正需要人工看图核验的文件（本班=4 张 PNG）与台账，不要放正文粘贴 HTML（它是粘贴链路的中转物，不是审阅对象）；稿件本身走 manuscript_path。d77 实测：去掉 HTML 后准入受理并 PASS，candidate_sha256 与磁盘主稿 sha 逐字一致。
evidence: docs/promotion/_d77_publish.py（admission 相位只传稿件+4 图+台账，不再传 paste HTML）；回执 docs/promotion/receipts/d77-admission.json（qualification=PASS，candidate_sha256=641659e1…）；首次被拒的回执 reason_code=review_material_file_too_large
tags: [Rule28, 宿主准入, artifact_paths, 文章发表, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-11T13:54:19.173014+08:00"
updated_at: "2026-11-11T13:54:19.173014+08:00"
---