---
title: LLM 429/1311 属套餐权限时：要读 request.meta 的实际模型，不能信配置里的模型名
scenario: LLM 调用 429 且错误文案是 provider 自定义「订阅套餐暂未开放某模型变体权限」，需要判定是限流、Key 问题还是模型变体权限问题，并确定切换目标
root_cause: ""
solution: "不猜：先读事件日志的 request.meta 实际 model + provider.transport.settled 的 model_id/provider_code，区分限流 vs model_permission；再查本地 provider 注册表 models[].note 的审批状态。确认是变体权限后换 provider 的模型（本次 minimax/MiniMax-M3.1-Flash），并用「服务级模型覆盖」把切换限定在目标服务，不动全局默认。"
evidence: "实测证据：(1) data/event_logs 企微会话 request.meta 的 model=\"glm/glm-5.3-flashx\"，provider.transport.settled provider_code=1311、attempt_kind=primary；(2) runtime.toml [llm] model=\"glm/glm-5.3\" 与实际请求模型不一致；(3) data/providers.local.json glm provider models[\"glm-5.3-flashx\"].note 记「本 key 实测 chat 仍 429/1311，试用获批前调用会如实失败」；(4) 切 minimax 后直连 https://api.minimax.chat/v1/chat/completions HTTP 200、tool_calls 正常；(5) resolve_effective 实测 wecom=minimax/MiniMax-M3.1-Flash、其余服务仍 glm/glm-5.3。"
tags: [llm, provider, 429, model_permission, 诊断, runtime]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T11:33:35.899237+08:00"
updated_at: "2026-10-30T11:33:35.899237+08:00"
---

症状：LLM 调用返回 429，error body 里是 provider 自定义中文文案（如 code=1311「当前订阅套餐暂未开放GLM-5.3-FlashX权限」），表面看像"限流"或"Key/模型名配错"。

诊断要点：配置里的模型名 ≠ 实际请求的模型名。必须读事件日志 request.meta 的实际 model 字段、provider.transport.settled 的 model_id 与 provider_code，才能确定是哪一层把模型解析成了别的变体。本次实证：runtime.toml 写 model="glm/glm-5.3"，实际请求 model="glm/glm-5.3-flashx"、provider_code=1311 → 是订阅套餐无该变体权限（model_permission），不是限流。

配套事实：本地 provider 注册表 data/providers.local.json 的 models 条目里自带 note 记录了该变体的审批状态与实测结论（如「本 key 实测 chat 仍 429/1311…试用获批前调用会如实失败」）——先读注册表再猜。

反例（本次踩到）：只看配置与错误码就断言"网络/Key/模型名配置问题"，会误判为改 Key；也只看"当天有 107 次 glm/glm-5.3 成功"就认为不是模型问题，漏掉间歇性变体解析。

复用要点：429 先分两类——provider_code 语义（限流 vs 套餐/权限），再对照 request.meta 实际模型；两者都指向"变体权限"时，换一个 provider 的模型（本次 minimax/MiniMax-M3.1-Flash）而不是改 Key。

关联：见 method:per-service-llm-model-scope（本轮实现的 [llm.<service>] 服务级模型覆盖）。