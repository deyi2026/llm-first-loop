---
title: MiniMax TokenPlan 订阅 key 无法调用 H3 系列视频生成接口（产品级限制）
scenario: 想用 MiniMax TokenPlanUltra 订阅额度调用 /v2/video_generation 生成视频（MiniMax-H3-Max）
root_cause: ""
solution: "不可行：TokenPlan/Credit 计费的 key 被 API 明确拒绝调用 H3 系列模型（错误码 2013，HTTP 400），与余额无关，是产品级限制。需单独开通按量付费（\"按量购买 API\"）后才能调用。不要在 TokenPlan key 上重试或加大余额。"
evidence: "execute_command 回执 /tmp/mm_v2_test.json：{\"type\":\"error\",\"error\":{\"type\":\"bad_request_error\",\"message\":\"invalid params, TokenPlan 或 Credit 暂不支持 MiniMax-H3 系列模型 (2013)\",\"http_code\":400},\"request_id\":\"06fb4583217b1b7a685556f3cb388c1a\"}；参数依据 https://platform.minimax.cn/docs/api-reference/video-generation-v2-create"
tags: [minimax, video-generation, tokenplan, api-billing, h3-max]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T00:16:44.946643+08:00"
updated_at: "2026-09-18T00:16:44.946643+08:00"
---

实测（2026-09-18）：用 .env 中 MINIMAX_API_KEY（sk-cp- 前缀，125 字符）POST https://api.minimax.cn/v2/video_generation，body={"model":"MiniMax-H3-Max","content":[{"type":"text","text":"..."}],"resolution":"480P","duration":5,"ratio":"16:9"}，返回 HTTP 400 错误码 2013，message="invalid params, TokenPlan 或 Credit 暂不支持 MiniMax-H3 系列模型"。鉴权通过（非 401/1004），说明 key 有效但账户计费类型为 TokenPlan/Credit，H3 系列（H3 与 H3-Max）均被产品级限制拦截，1008 insufficient_balance 不会出现。若要调视频生成需开通/购买"按量购买 API"（官方文档明示 H3/H3-Max 需按量付费）。最小参数组合：H3-Max 分辨率仅 480P/768P（无 2K），时长 5~15s（无 4s），纯文生视频 ratio 必填且不可为 adaptive。请求被 400 拒绝=未创建任务=零费用。