---
title: 并发会话同稿推送：读发布 state log 的 submitted 记录拦截重复发布
scenario: 头条图文发布链路中，另一会话（排期班次）正在对同一篇稿执行 open→prepare→title→ai→verify→preview→confirm；本会话因配图排版修订重跑 build 后在新开 tab 重贴并 preview，预览浮层的「确认发布」按钮已可见且可点。
root_cause: 同一工作区同一稿件可能被两个会话同时推进：排期班次会话与用户指令会话重叠。发布动作的幂等键不在脚本里，而在 receipts/<稿>-toutiao-local.json 的 log（phase=submitted）与作品管理页标题计数上。
solution: "动手前先读 receipts/<稿>-toutiao-local.json 的 log：若已出现 phase=submitted（AFTER_URL=profile_v4/graphic/articles），说明同一篇已被提交——禁止点「确认发布」，立即关闭自己开的 tab（CDP GET /json/close/<target_id>），修订后的产物（新版 HTML/图）留库不重复发布；随后刷新作品管理页，用 body.innerText.count(TITLE)==1 确认没有第二篇同标题。当前性验证：跑 `python3 -c \"import json;log=json.load(open('docs/promotion/receipts/daily47-toutiao-local.json'))['log'];print([e.get('phase') for e in log])\"` 应看到含 'submitted'；复现查重：在作品管理页 tab 执行 `document.body.innerText` 后统计标题出现次数，应为 1。"
evidence: "2026-10-31 daily47 实测：另一会话（会话 902721d7）13:42:21 在 state log 记 submitted；本会话 13:42:58 起在 tab 740800E6 跑完 prepare→title→ai→verify(GATE PASS chars=2908/imgs=8/captions=4)→preview（CONFIRM_BTNS x=862,y=721），读到 submitted 后未点确认发布并关闭该 tab；13:49 作品管理页刷新后同标题计数=1（d47 已发布，展现 1）。"
tags: [头条发布, 并发, 重复发布, 幂等, state-log]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T13:51:11.977815+08:00"
updated_at: "2026-10-31T13:51:11.977815+08:00"
---