---
title: Rule28 准入送审稿件 md：markdown 表格会被页面拆成单元格行，必须先改成逐行正文句
scenario: 发布前用 review_admission(kind=article_publish) 送审稿件，正文含 markdown 表格
root_cause: 宿主准入的稿件/页面一致性检查是逐行文本比对；头条编辑器把 markdown 表格渲染成单元格行（每个单元格一行），markdown 源行（如 `| 攻击者能看到什么 | 命中率 |`）在页面里不存在对应行，导致 match_ratio 掉到阈值以下
solution: 准入前把稿件正文里的 markdown 表格逐行改写成「小标题：数值。」形式的正文句，使稿件正文行与页面可见正文逐行一致，再送审即可通过；送审对象可以直接是稿件 md，不必是页面可见正文 txt。当前性验证：改写后跑 `grep -c '^|' docs/promotion/20261103-lfl-daily-55.md` 应为 0，且 `grep -c '命中率 14.53%' docs/promotion/20261103-lfl-daily-55.md` 应为 1；准入以 review_admission(status) 回执 qualification=PASS 为准
evidence: "docs/promotion/receipts/daily55-admission.json、docs/promotion/STATUS-20261103-daily55.md 第六/十一节；首轮准入回执 manuscript_page_text_mismatch match_ratio=0.7821 threshold=0.9，改写两张表后同一路径一次通过（child_id=subagent_d371e3c93d47, qualification=PASS）"
tags: [rule28, admission, toutiao, markdown-table, publish]
source:
  note: d55 早班实测
  work_unit_id: daily55-publish
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T09:57:01.831612+08:00"
updated_at: "2026-11-03T09:57:01.831612+08:00"
---