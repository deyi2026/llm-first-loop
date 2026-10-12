---
title: 第三方 LLM 网关（Sub2API）故障分层诊断法：DNS/TLS 通但源站无响应 = 服务商侧故障
scenario: "LLM provider 网关（如 ai.mxnook.com 这类 Sub2API/Cloudflare 边缘代理）连不上：dashboard 打不开、API 报 522/超时；用户问\"是不是我这边的问题\"。"
root_cause: 第三方转发网关（Cloudflare 边缘 + origin 源站架构）中 origin 无响应，边缘超时返回 522；DNS/TLS 在边缘即完成，故 DNS/TLS 正常但请求无响应。
solution: 分层诊断四步：①DNS：python socket.gethostbyname 或 nslookup，快=正常；②TLS：curl -w 'time_appconnect'，<0.5s=边缘可达；③请求响应：curl --max-time 12 看是否收到字节（0 字节 + HTTP 000 = 源站无响应）；④对照：同环境测 api.deepseek.com/minimax/baidu 秒回 = 本地网络正常。判定：DNS+TLS 通但请求无响应 → Cloudflare 边缘连不到 origin，属服务商侧故障（源站宕机/过载/上游断连），本地无法修复。处置：注册 schedule 定时重测（如 10-15 分钟一次）；临时切其他 provider；长期不可用考虑 providers.json 下线或换网关。注意诊断命令别串行多个 curl（会整体超时），每个加 --max-time 单独跑。
evidence: 2026-08-19：ai.mxnook.com DNS 0.003s/TLS 0.19s 均正常，请求 12s 0 字节（HTTP 000），对照百度 200/deepseek 401/minimax 308 秒回；连续多次重测仍超时。
tags: [522, 网关故障, Sub2API, grok, 分层诊断, mxnook]
source: {}
status: active
created_at: "2026-08-19T13:33:32.850412+08:00"
updated_at: "2026-08-19T13:33:32.850412+08:00"
---