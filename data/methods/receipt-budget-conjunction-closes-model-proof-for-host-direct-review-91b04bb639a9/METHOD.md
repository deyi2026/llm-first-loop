---
method_id: receipt-budget-conjunction-closes-model-proof-for-host-direct-review-91b04bb639a9
name: receipt-budget-conjunction-closes-model-proof-for-host-direct-review
description: Host 直调型审查子任务被要求出具『实际使用模型 / 是否 fallback』证据时，权威闭包是回执预算字段的合取：start/status 的 models 主备清单、async_retry_max、attempts 计数，加上一次运行时 model_fallback 观测维度。工作区事件流按模型名或 child_id 检索只会命中兄弟会话的路由噪音；Host 直调不在 agent action_trace 留 per-call provider 事件，该缺失应作为证据边界如实披露，而不是继续换词检索。fallback 为真或 attempts>0 时转入披露分支，不得宣称主选。
aliases: 怎么证明审查真用了指定模型, 审查没有模型调用日志怎么交代, 有没有换过模型怎么查, 事件流里全是别的会话在切模型, 子审查模型归属取证
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0bf4a1f9-e8ff-46ff-8388-7cefc89e47c9:0:8d35aa7a98014349853b
evidence_refs: learning:learn:72c8b4c992e8
created_at: 2026-11-12T12:53:39.629198+08:00
updated_at: 2026-11-12T12:53:39.629198+08:00
---
## Trigger
任务要求证明审查/准入子任务实际使用的模型或是否发生 fallback，而 start/status 回执已含 review_budget（models 主备清单、async_retry_max、attempts 计数）；或在工作区事件流按模型名/child_id 检索 provider 事件只命中兄弟会话路由噪音时

## Discriminator
回执 budget 已给出主备模型清单且 attempts=0（备选从未触发）、async_retry_max=1；architecture_status(model_fallback, runtime) 回 active=false 且 from/to/reason 全 null；subagent_result 显示 rounds=1、tools=0——三者合取在取证开始前就已闭合『用了主选、无 fallback』，继续找 per-call provider 日志是在不存在的通道里搜索

## Short path
- start 后核对 candidate_sha256 回显，按 waiting_protocol 轮询 status 至非 pending 终态并核对 SHA 再次回显
- 终态回执缺 VERDICT/P0/P1/P2 → subagent_result(child_id) 取子代理回答与结论行，一次即足
- 缺模型证据 → 不重发 status、不做工作区级模型名/child_id 事件检索；直接读手中回执的 budget 字段（models、async_retry_max、attempts）
- 一次 architecture_status(dimensions=[model_fallback], scope=runtime) 验证运行时零 fallback 事件
- 三通道一致（主选 + attempts=0 + fallback inactive）且与 rounds=1/tools=0 自洽 → 判定主选被用、无 fallback，交付中明示证据边界：Host 直调无 per-call provider 日志，结论基于回执合取
- 停止取证；逐字 terminal 回执用已取得的终态回执原文，不追加复验调用

## Stop conditions
- models/attempts/model_fallback 三通道一致且与子代理结算（rounds=1、tools=0）自洽 → 停止取证
- model_fallback.active=true 或 attempts>0 → 停止合取推断，转入如实披露分支（备选模型被用过）
- 用户所需交付物（terminal 回执、VERDICT、P0/P1/P2、模型结论、证据边界披露）已全部取得 → 停止

## Verification
- 核对 attempts 与 async_retry_max 的语义：attempts=0 且 retry 上限为 1 表示备选模型从未被调用
- 核对 model_fallback 的 from/to/reason 均为 null 且 active=false
- 核对子代理结算 rounds=1、tools=0 与 Host 直调单轮一致；candidate_sha256 在 start/终态回执/审查正文三处一致

## Counterexamples
- architecture_status 显示 fallback active=true（如 glm→minimax 切换）：回执合取不再成立，必须如实披露 fallback，此时按 child 定点追传输日志才正当
- 审查由 agent 子代理执行（tools>0、多轮）：action_trace 中存在其执行事件，按 child 会话定点检索合理，不应只靠回执闭包
- 任务硬性要求逐调用 provider 日志且环境存在 per-child transport log 通道：应直接按 child_id 查该通道取证，而非以合取推断替代
- 闸版本回执不含 budget 字段：合取无从谈起，需先定位能供应模型信息的观测通道
