---
method_id: steer-policy-rejection-makes-format-retry-outcome-predetermined-6532932a5db0
name: steer-policy-rejection-makes-format-retry-outcome-predetermined
description: 门禁要求独立审查子代理终态通过严格结构化解析（raw JSON），但输出契约未写入 spawn 任务模板时，唯一补救是 post-spawn 注入。一旦注入通道（agent_message steer / agent_followup）回执是策略性拒绝（review_isolated 类），契约永远到不了 child；叠加同模型+同模板+先前同款 child 已因 fenced 格式 FAIL，则重审的解析结局在通道被拒那一刻就已确定。此后不再把该轮当『修复尝试』执行或汇报，只按指令完成一次真实验证，并按通道/契约结构缺口收口上报：不换通道变体、不开第三轮、不伪造资格字段。
aliases: 格式提醒发不进子代理, 重审前先确认契约递得到, 第二次还是review_not_structured, steer被隔离策略拒了, 别白跑注定挂parse的重审, spawn任务书没写raw JSON要求
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:664:683ab70885bdec0d8cd0
evidence_refs: learning:learn:832d352da55a
created_at: 2026-11-17T09:57:21.014864+08:00
updated_at: 2026-11-17T09:57:21.014864+08:00
---
## Trigger
受管门禁要求审查子代理终态必须通过严格结构化解析，此前同模型/同 spawn 模板的 child 已因叙述+fenced JSON 被 FAIL（如 review_not_structured），当前补救方案的成功完全依赖在子代理 running 期间通过 steer 通道向隔离 child 注入格式契约。

## Discriminator
steer 回执本身是策略性拒绝（『review_isolated 禁止父会话 steer』、followup 同禁）而非瞬态错误：它证明契约不可送达。在收到该回执的瞬间，结合『spawn 模板无契约』与『先前同款 fenced 终态』两个当时已知事实，第二次格式 FAIL 在等待结束前即可预判，无需等 child 终态。

## Short path
- 执行补救前，把『通道可用』当作待回执确认的假设而非既定事实；第一次注入本身就是对它的最廉价探测
- steer 回执为策略拒绝的瞬间，立即把在途重审重新定性：不是修复尝试，而是被指令规定的确认性验证运行；预写终局分类=通道/契约结构缺口，非审查质量问题
- 按最小协议走完被指令要求的验证：一次定长阻塞等待至终态（不即时短轮询），一次真实 Host parser 校验
- 预判的格式 FAIL 落地后按停机规则 HOLD；终态报告以结构缺口开头（spawn 模板缺输出契约、两条注入通道均被策略禁止），提议宿主侧修复（任务书内置 raw-JSON 契约、parser 放宽）或人工豁免；不伪造 verify_ref、不循环重审

## Stop conditions
- steer 策略拒绝 + spawn 模板无契约 + 先前同款格式 FAIL 三者同时成立：不再尝试任何通道变体，不开第三轮审查
- Host parser 已按指令真实校验一次且 FAIL：HOLD，转宿主/人工裁决
- 结构化终态通过 parser：门禁正常流转，立即停止

## Verification
- 资格结论只认真实 Host parser 回执，不因 child 正文实质 PASS（P0=0/P1=0）而替代资格 PASS
- 结构缺口断言必须逐条引用两类通道的策略拒绝回执原文，不得靠推断
- 确定性复现断言须同时引用三事实：同模型、同 spawn 模板（契约缺失）、先前 fenced 终态

## Counterexamples
- steer 回执成功送达（无策略拒绝）：契约已到 child，格式结局未定，重审仍是真实的修复尝试，不应预判失败
- spawn 任务书本身已内置结构化输出契约：无需 steer；此时格式失败属模型遵从性漂移，走准入合同/重发路线，不适用本方法
- parser 宽松（可抽取 fence 内 JSON 或容忍叙述）：格式层不是门，本方法无适用对象
- 先前 child FAIL 是内容原因（真实 P0/P1）而非输出格式：复现预判不成立，按内容缺陷流程处理
