---
title: 末轮改稿或重贴后，先前的 review_admission 冻结指纹失效，必须重新 start 并等终态 PASS
scenario: 长文发布链路里，内容审稿最后一轮要求改稿（改 md 文字、改图、重建 HTML）并重贴编辑器页面，之后拿之前那次 review_admission 的 PASS 去 confirm。
root_cause: ""
solution: 最后一次改稿/重贴之后必须重新 start 一次 review_admission 并等 status 终态 PASS，再写准入回执（frozen_md_sha = 当前 md SHA）后 confirm；target_name 填「确认发布」；多 page 先显式 target_id 换绑。
evidence: receipts/daily59-admission.json（frozen_md_sha=500c0de0…、host_child_id=subagent_dca105fb7ccd、candidate_sha256=251ed424…）；作废的另一次 child_id=subagent_8d03b8693d2d（candidate 78b8b8f6…）；_d59_publish.py 的 confirm 阶段断言 frozen_md_sha==digest(MD)
tags: [头条发布, review_admission, RULE-AI-28, 准入]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T13:40:53.608855+08:00"
updated_at: "2026-11-04T13:40:53.608855+08:00"
---

本班 `review_admission(action=start, kind=article_publish)` 成功签发 PASS，但**这次资格在发布前就作废了**：签发后又按审稿意见改了 4 处措辞并重贴了页面正文，于是先前的冻结指纹（稿件 SHA + 页面可见正文指纹）已经对不上当前产物。若直接用旧回执 confirm，要么被 `frozen_md_sha` 断言挡住，要么等于拿旧审查结论发新稿。

本班两次准入的对照：
- 作废：child_id=subagent_8d03b8693d2d，candidate_sha256=78b8b8f6…（覆盖末轮改稿前的稿件与页面）
- 生效：child_id=subagent_dca105fb7ccd，candidate_sha256=251ed424…（覆盖终稿 md SHA 500c0de0… + 终稿页面正文）

判据：**最后一次改动（改稿或重贴）之后签发的准入才是有效准入**。顺序固定为：改稿 → 重建 HTML → 重跑审计 → 重贴 → 点预览 → 重新 `review_admission(start)` → 等 `action=status` 终态 PASS → 写准入回执（frozen_md_sha 必须等于当前 md SHA）→ confirm。

另外两点已验证：`target_name` 必须填**页面按钮标签「确认发布」**（填文章标题会被拒：publication_target_name_required）；CDP 多 page 时先 `browser_perceive(action=snapshot, target_id=…)` 显式换绑到本班编辑器 tab。

当前性验证：跑 `python3 -I -c "import hashlib,json;from pathlib import Path;a=json.load(open('docs/promotion/receipts/daily59-admission.json'));print(a['frozen_md_sha']==hashlib.sha256(Path('docs/promotion/20261104-lfl-daily-59.md').read_bytes()).hexdigest())"` 应为 True；`review_admission(action=status, child_id=subagent_dca105fb7ccd)` 应回 qualification=PASS。