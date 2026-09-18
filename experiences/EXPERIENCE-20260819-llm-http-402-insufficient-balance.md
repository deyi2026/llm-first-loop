---
title: LLM HTTP 402 Insufficient Balance 故障识别与处置：充值即恢复，无需重启
scenario: "LLM 调用报 HTTP 402 Payment Required / Insufficient Balance；多个会话同时\"卡住出错\"（如修复任务中断、飞书不回复、空输出），exception_log 连续出现 402。"
root_cause: deepseek 账户余额耗尽；provider 对余额不足返回 HTTP 402，客户端如实报错不降级不静默。
solution: "①识别：exception_log 中 402 + \"Insufficient Balance\" 即 provider 账户余额耗尽（区别于 LLMTimeoutError/Concurrency limit/NetworkError）；所有走该 provider 的调用（当前会话/飞书/其他任务）会同时失败——\"那边卡住\"大概率是 402 掐断而非任务本身问题。②处置二选一：充值（恢复低成本默认链路，最省事）或 switch_model 切其他 provider 应急（grok-4.6 cost=mid / MiniMax-M3 / local 免费，需用户拍板——涉及钱包与缓存窗口重置）。③充值后自动恢复，无需重启、无需切模型；验证方式：新轮次 LLM 正常返回即解除，exception_log 中残留 402 为历史记录不再新增。④处置顺序：先解决 402 再继续任务，否则修到一半又是空输出。"
evidence: 2026-08-19 现场：4 条连续 402 后用户充值，当前轮 LLM 正常返回；architecture_status exception_log 残留 402 无新增。
tags: [402, 余额不足, LLM异常, 故障处置, 充值]
source: {}
status: active
created_at: "2026-08-19T12:26:20.342384+08:00"
updated_at: "2026-08-19T12:26:20.342384+08:00"
---