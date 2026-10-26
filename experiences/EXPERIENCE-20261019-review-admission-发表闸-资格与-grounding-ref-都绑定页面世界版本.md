---
title: review_admission 发表闸：资格与 grounding_ref 都绑定页面世界版本
scenario: "LFL review_admission(action=start, kind=article_publish) 签发一次性发表资格后用 browser_operate 点击\"发表\"，多次被拒（review_admission_blocked / identity_unstable_objects / duplicate_action_id）"
root_cause: ""
solution: "【两个独立约束】(1) 资格绑定 = {parent 会话, kind, target \"article_publish:<按钮名>\", sha=页面可见文本+url+发布控件的 digest}。签发后若页面任何可见文本变化（哪怕只是草稿历史时间戳跳动），点击会被 review_admission_blocked 拒绝；必须重新走 review_admission(action=start) → status。(2) grounding_ref 属于特定 snapshot。复用旧 snapshot 的 ref 会触发 identity_unstable_objects 或 duplicate_action_id；必须在签发资格后、点击前重新 browser_perceive(snapshot) 取最新 ref。【排查纪律】browser_operate 回执被压缩时不给 reason，直接读回执存储拿真实原因：python3 -c \"import json,glob,os; f=sorted(glob.glob('data/browser_semantic_operation/*/*.json'),key=os.path.getmtime)[-1]; d=json.load(open(f)); c=d['content']['clauses'][0]['action_receipt']; print(c['status'], c.get('retry',{}).get('reason'), c.get('identity'))\"，拿到原因再动手，不要靠推断。同参重复点击会被幂等去重返回 duplicate_action_id，此时改 grounding_ref 而不是改参数。当前性验证：下次复现前先跑上面这条命令确认 receipt 路径结构未变（若报 KeyError 说明 clauses 结构已改，需重新定位）。"
evidence: "回执 evidence://v1/9248ae29（identity_unstable_objects）、evidence://v1/0c2865fd（duplicate_action_id）、evidence://v1/8d4f9aa4（status=completed 成功）"
tags: [RULE-AI-28, review_admission, browser_operate, grounding_ref, 排查纪律]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-19T16:44:04.424561+08:00"
updated_at: "2026-10-19T16:44:04.424561+08:00"
---