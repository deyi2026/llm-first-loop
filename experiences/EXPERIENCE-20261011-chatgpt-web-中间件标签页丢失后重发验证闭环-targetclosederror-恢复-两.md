---
title: chatgpt-web 中间件标签页丢失后重发验证闭环（TargetClosedError 恢复 + 两修复生产生效）
scenario: "ChatGPT-web 中间件（chatgpt-web/web-gpt，lfl-model-0005）在 web 服务重启或用户手动关闭专用标签页后派发消息，失败为 TargetClosedError: Page.goto；需判断是否可恢复、如何恢复与如何验证修复生效。"
root_cause: ""
solution: "1) 该错误是标签页丢失的机械结果，target 完全消失后 surface.open() 自动走 _create_owned_page 在项目 URL 重建标签页并续新会话段（binding conversation_id=null → 新段），无需人工干预浏览器。2) 重发标准流程：POST /api/v1/chat/queue 入队（session_id+message，冻结事实）→ POST /api/v1/chat/queue/dispatch 领取 → POST /api/v1/chat/stream 带 queue_id 与同值冻结字段消费；队列项终态 completed 即闭环。3) 验证两修复生效的日志特征：chatgpt_transport \"cache_prefix stable_chars=... payload_chars=...\"（段重建成功）与 \"harvest fallback: parsed literal lfl-model-response fence\"（纯文本兜底收割路径）。当前性验证：tail -c 200000 data/web.log | grep \"harvest fallback\" 应见当次时间戳记录；python3 -c \"import json;print([i for i in json.load(open('data/human_turn_queue.json')) if i['queue_id']=='<qid>'][0]['status'])\" 应为 completed。"
evidence: "data/human_turn_queue.json q_479c02d58b1e status=completed run_error=None；/tmp/sse_requeue.log done 事件（rounds=1, model=chatgpt-web/web-gpt）；data/web.log 16:52:04 chatgpt-web cache_prefix stable_chars=43994 payload_chars=99682；16:52:15 chatgpt-web harvest fallback: parsed literal lfl-model-response fence (rendered_code_blocks=0)"
tags: [chatgpt-web, middleware, segment-rollover, queue-requeue, surface-recovery]
source:
  action_id: svc-59f21337215444f5a1b7b743608e5a7c
  commits: "['2059e84d4', '8128e71dc']"
  generation: 233
  queue_id: q_479c02d58b1e
  session_id: 9a7c8ffd-c8e8-4c69-861f-22d29b394dba
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T16:53:31.325669+08:00"
updated_at: "2026-10-11T16:53:31.325669+08:00"
---

现象链：16:08 web 重启把 chatgpt-web 中间件专用标签页一并带走，16:12 派发"继续"时 surface.open() 在页将关未关窗口执行 Page.goto 抛 TargetClosedError（open() 的 except 只捕 BrowserSurfaceLeaseError），队列项 failed。target 彻底消失后重试即走 _create_owned_page 重建标签页。验证事实（16:51-16:52）：重新入队 q_479c02d58b1e → dispatch 领取 → /api/v1/chat/stream（带 queue_id、冻结字段回传）消费 → 单轮 done；web.log 显示 cache_prefix stable_chars=43994 payload_chars=99682（新会话段 6 重建），且 "harvest fallback: parsed literal lfl-model-response fence (rendered_code_blocks=0)"——8128e71dc 的纯文本兜底收割在生产首次触发即成功，同时证明 2059e84d4 折叠展开修复随 233 代生效。