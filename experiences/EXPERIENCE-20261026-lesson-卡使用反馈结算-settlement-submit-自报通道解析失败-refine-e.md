---
title: lesson 卡使用反馈结算：settlement_submit 自报通道解析失败，refine_experience record_use 同 ref 全部成功
scenario: LFL 推广任务收尾结算：对本班实际使用的 5 条 lesson 卡（头条粘贴图注双写/懒加载/已发表判据/ProseMirror 六坑/argv 换行坑）提交使用反馈
root_cause: ""
solution: "lesson 卡结算失败（ref not found）时不要换格式盲试第三批；改用 refine_experience(action=record_use, experience_id=同一 ref) 逐条回执，同样进 ledger。method 卡走 settlement_submit 正常（本班 2 条 committed）"
evidence: settlement_submit 回执（committed=2 pending=0 failed=5，5 条 reason=self_reported ref not found）与随后 5 条 refine_experience record_use 成功回执（submission_hash 0652d052…、5ec88096…、6aefae0b…、6d2202a8…、30d344ac…）
tags: [settlement_submit, refine_experience, lesson卡结算, 知识回执, 推广任务]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T13:48:58.887240+08:00"
updated_at: "2026-10-26T13:48:58.887240+08:00"
---

现象：settlement_submit 自报 lesson 类卡片（ref 形如 experience:EXPERIENCE-YYYYMMDD-中文标题）连续两批共 5 条全部 "self_reported ref not found"，而 search_records(kind=lesson) 展示的 experience_ref 与提交串完全一致；随后对同样 5 个 ref 逐条 refine_experience(action=record_use) 全部 ledger_recorded=true。结论：lesson 卡的知识使用反馈走 refine_experience record_use 通道可靠；settlement_submit 的自报解析对 lesson 类 ref 存在解析缺口（待架构侧确认）。n=1 批（2026-10-26 午班，5 失败→5 成功对照）。复现：对任一 lesson ref（例：experience:EXPERIENCE-20261025-头条-data-uri-粘贴链-图注必须-alt-独立-p-段双写-verify-captions）跑 settlement_submit（kind=experience, self_reported=true）应得 reason="self_reported ref not found"；对同一 ref 跑 refine_experience(action=record_use) 应得 ledger_recorded=true。当前性验证：先 search_records(kind=lesson, query=图注 alt) 确认该 ref 仍存在再复现。