---
method_id: native-logs-before-heavy-probes-on-live-shared-services-5bcd812f372c
name: native-logs-before-heavy-probes-on-live-shared-services
description: 怀疑配置的模型名/标识符过期时：先用服务端 /v1/models、注册表等权威解析源确认失配并拿到真实参数（如 n_ctx）；若日志显示解析失败走了静默回退（default/ 前缀），则从回退默认值与真实上限之差推导行为后果（预算失真→不裁剪→溢出），并直接查消费方自身事件日志验证损害是否已发生。不要向承载在跑任务的共享服务发大 payload 合成探测——当"服务端只有一个模型且错误名请求已被成功应答"已知时，探测回答不了新问题，只会制造"故障是否由我引发"的因果混淆，迫使额外取证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5693816b-bf5b-467a-8a25-a8f48a50e29b:60:bf7e865ce7f7dfac0f49
evidence_refs: learning:learn:9a990bc2b5be
created_at: 2026-09-22T16:08:03.726958+00:00
updated_at: 2026-09-22T16:08:03.726958+00:00
---
## Trigger
用户质疑某配置标识符（模型名/endpoint/资源 id）与实际运行时不符，且该服务正承载在跑任务、并存在可读的事件/审计日志时。

## Discriminator
探测前已知两条事实：服务端 /v1/models 只列出一个模型（n_ctx=65536），且事件日志中带错误模型名（default/ 前缀）的请求已获成功 llm_result——这两条已判定"服务端忽略 model 字段、用唯一模型应答"，剩余未知量（预算失真是否已造成损害）只能由任务自身日志回答，合成探测无法提供新信息。

## Short path
- 一次捆绑调用取进程命令行 + /v1/models + 任务 env：确认配置名不在权威模型清单中，同时拿到真实 n_ctx。未知量：名字是否错、真实模型是什么。
- 查注册表：确认该名不可解析、正确名及其 context；记录回退默认值(1000000)与真实上限(65536)之差。未知量：错误名的解析后果是什么。
- 查事件日志中模型串前缀（default/）与成功的 llm_result：证实静默直通回退、服务端容忍错误名。未知量：为什么配置错了还能跑。
- 由"回退→预算按默认 1M→不做裁剪"推出迟早溢出的假设，直接 tail/grep 最新任务日志的 llm.interrupted / program.final / error_digest 验证损害是否已发生。未知量：损害是否已发生。确认后停止，不做合成探测。
- 仅当无任何原生日志可用时，才用最小 payload 探测，并从响应的 model 字段直接读出答案。

## Stop conditions
- 失配（权威源清单）、回退机制（日志模型串前缀）、损害（error_digest 原文）三者均有直接证据后，立即停止发现动作。
- 若任务日志无异常且任务仍在跑：报告风险与正确配置值即可，不主动发探测复现故障。

## Verification
- 最终结论中每条机制断言（名称不存在、default/ 回退、预算 1M vs 65536、任务死亡原因）都能指回具体来源：/v1/models、注册表条目、事件日志字段、error_digest 原文。
- 若确实做过探测：确认 payload 最小、未与在跑任务争抢上下文/槽位，并能明确论证探测与观测到的故障无因果关系；否则视为未遵守本方法。

## Counterexamples
- 全新部署、无任何历史日志：此时最小合成探测是验证服务行为的正确且必要手段，本方法不适用。
- 服务端加载多个模型、model 字段参与路由：不能由"只列出一个模型"推出"忽略 model"，必须真实探测路由行为。
- 用户只问名字对不对、且无在跑任务：确认失配并给出正确名即停止，无需追查回退后果。
- 可读日志属于过期会话或与当前任务无关：不能作为当前状态的权威证据。
