---
title: help_request 的 need=block 是全局停工闸，不是「这件事很重要」的强调
scenario: 在多会话共享仓库里想用 help_request 提醒某个 lane 的 owner 收口时，顺手选了 need=block（因为「这件事确实在阻塞我」）。
root_cause: ""
solution: |
  提醒/催办类跨会话消息一律用 need=info。只有确实要求「所有合并停摆等我」时才用 need=block。若已误发：立刻 help_resolve(id, decision=declined, response=说明撤回原因) 把它移出 pending/，再用 help_inbox(need=block) 核 blocking=0，最后以 need=info 重投。方向不要搞反：need 的语义是「请求方要什么」，不是「这件事有多严重」。
  
  当前性验证（2026-11-09 10:47 实测，复现方式）：grep -n 'need=block' src/llm_loop/introspection/lane_gate.py 仍应命中 S1-08 的全局判据；随后 help_inbox(need=block) 在无阻塞项时应返回 blocking=0。
evidence: "help_request 回执（本条 need=block 明确警告「S1 第 8 条机检会因此不放行该 lane 合并」）→ 撤回后 help_inbox(need=block) 回执 pending=6 blocking=0；lane_gate.py:459-474 源码：S1-08 判据为「收件箱中不存在任何 need=block 的未决请求」，不区分 lane/session、不区分发送方。"
tags: [help_request, need=block, lane_gate, S1-08, 跨会话协作, 反直觉闸门]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-09T10:48:25.685789+08:00"
updated_at: "2026-11-09T10:48:25.685789+08:00"
---