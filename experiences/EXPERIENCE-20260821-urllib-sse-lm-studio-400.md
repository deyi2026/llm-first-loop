---
title: 本地大模型工具调用基准方法 + urllib SSE 触发 LM Studio 交替 400 陷阱
scenario: "需要实测本地大模型（LM Studio + qwen3.8-27b 等）工具调用能力与\"保持前缀+小信息量\"策略效果时；或 harness 对 local 模型连续请求出现 HTTP 400 空 body 时。"
root_cause: "urllib.request 逐行迭代（for raw in r）读取 SSE 流的方式被 LM Studio 判定为客户端提前断开（server 日志实锤 \"Client disconnected. Stopping generation\"），服务端中断生成且连接未释放，下一请求在模型 busy 时到达即 400；http.client/httpx 完整读取不触发。"
solution: "① 基准必须走真实接入协议：本地模型（wire_protocol=lms-chat）走 /api/v1/chat + input 模态数组 + 文本工具协议（工具描述注入 + 模型输出 {\"tool\":..,\"args\":..} JSON，平衡括号解析），不是 OpenAI /v1/chat/completions tools 格式——两条路径行为可能完全不同。② HTTP 客户端陷阱：urllib.request 的 for raw in r 逐行迭代 SSE 流会触发 LM Studio \"Client disconnected. Stopping generation\" 判定，导致连续请求**交替 200/400**（奇数位成功偶数位拒绝，body 空）；http.client + resp.read() 一次性完整读取 6/6 稳定；httpx iter_lines 也稳定（3 连发全 200）。修复基准脚本 call() 用 http.client 复用连接+完整读取。③ 判定逻辑与 client.py _parse_text_tool_calls 逐字对齐（```json 围栏容错 + 平衡括号），避免测非真实路径。④ 归因标准：对照组逐字一致/唯一变量/N≥6 复现一致才可信——\"small 全过 large 全 400\"曾因请求顺序巧合（small 恰在奇数位）被误判为变量差异。"
evidence: "受控实验：urllib 3 连发 200/400/200（相位可随 UA 反转）；http.client 复用连接 6/6 全 200；httpx iter_lines 3/3 全 200；curl 独立进程 3/3 全 200。LM Studio server 日志 ~/.lmstudio/server-logs/2026-08/2026-08-21.1.log 13:36:12 出现 Client disconnected。修复版 v2 基准（http.client）24/24 无 400。job-7 数据存 data/audit/bench_v2_results.json。"
tags: [本地模型, 工具调用, lms-chat, SSE, LM Studio, 基准, 前缀缓存]
source: {}
status: archived
created_at: "2026-08-21T14:14:03.075615+08:00"
updated_at: "2026-09-06T00:19:02.697933+08:00"
---

本次专项目标：验证"保持前缀+小信息量让本地模型调用工具"经验的可复现边界。三个关键教训：① 基准要用真实协议（lms-chat 文本工具协议）而非 OpenAI tools 格式，否则结论不可迁移；② 客户端读取方式本身就能制造假故障（urllib SSE 逐行迭代→LM Studio 交替 400），修复后 24/24 全绿；③ 数据全绿时要怀疑是否"任务太简单/顺序巧合"，加严（嵌套参数/多工具/大上下文/真实历史）后 qwen3.8-27b 实测：格式 24/24 稳定，嵌套参数（send_email.schedule）4 组合全 fail 是真实边界，参数正确率 static/large 4/6 > static/small 3/6 但样本小未达显著。耗时 static(14s) < dynamic(20s) 差 ~30-40%，收益机制是"减少动态内容引发的额外思考"而非 KV 缓存跨请求复用。

## 2026-09-06 lifecycle review

该记录把 local 当前接入前提写成 wire_protocol=lms-chat；当前 data/providers.json 的 local provider 未配置 lms-chat，按现行 registry 默认走 openai。旧 urllib/SSE 陷阱保留为 LM Studio 历史兼容资料，不作为当前通用操作指南。
