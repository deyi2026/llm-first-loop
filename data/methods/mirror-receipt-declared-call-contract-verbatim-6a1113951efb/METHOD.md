---
method_id: mirror-receipt-declared-call-contract-verbatim-6a1113951efb
name: mirror-receipt-declared-call-contract-verbatim
description: 控制/派发类工具调用前，若最近一条系统回执已显式写出下一次调用的字段名与取值（如 next 指导中的 service_control(action=restart, target=..., expected_generation=N)），把该声明当作权威调用契约逐字照抄派发，而不是凭记忆、上一轮用法或跨工具类比重建字段名。若仍收到参数错误回执，按回执自带规则一次性修正全部被点名字段后重发；仅当类型/enum 仍不确定时才读一次 get_tool_schema。回执声明的受理≠完成：终态按回执给出的查询入口异步核对，受理即停。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1764:b368857e798e6ad21b9d
evidence_refs: learning:learn:ba0f0f72c9dc
created_at: 2026-10-09T13:58:34.142939+08:00
updated_at: 2026-10-09T13:58:34.142939+08:00
---
## Trigger
即将向控制/派发类多字段工具（尤其本轮首次调用）发起 dispatch，且最近一条工具回执中包含显式调用模板、字段名或 next 执行指导

## Discriminator
回执文本是否逐字给出参数名与示例取值（如 target=..., expected_generation=209）。存在即契约已由系统声明，字段名无需猜测、也无需先读 schema；缺失则本方法不适用，走常规 schema 预读路径

## Short path
- 派发前检查最近一条回执是否声明了下一调用的字段名/语法/取值
- 有声明：逐字复用其字段名与取值，一次性派发
- 声明不完整（缺类型/enum）：读一次 get_tool_schema 补齐后再派发
- 收到 missing=<field> 类参数错误回执：按回执要求一次性修正全部字段重发，不逐字段试探

## Stop conditions
- 回执返回 accepted/success 且回显字段与派发一致
- 回执声明该动作为异步/两阶段等待等设计行为：受理即停，改用回执给定的终态查询入口按需核对，不在本会话内反复轮询催促

## Verification
- accepted 回执回显的字段名与值与所派发内容逐字一致（如 target=web, generation=209）
- 本轮未再出现 missing=<field> 或参数契约类失败回执

## Counterexamples
- 回执只有模糊建议（'应重启落后服务'）而无确切字段名：应先读 get_tool_schema，不套用本方法
- 回执契约与当前 get_tool_schema 冲突（旧版本回执/工具已演进）：以当前 schema 为准，不信旧回执
- 回执建议的动作与用户当前目标无关：不因契约声明而盲从执行
- 同一工具本会话已多次成功派发且契约已被回执反复确认：无需每次逐字核对，避免仪式化开销
