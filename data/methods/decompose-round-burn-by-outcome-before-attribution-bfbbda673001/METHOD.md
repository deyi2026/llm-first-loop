---
method_id: decompose-round-burn-by-outcome-before-attribution-bfbbda673001
name: decompose-round-burn-by-outcome-before-attribution
description: 当 loop/子代理回执显示 rounds 打满上限而真实产出（工具执行/入档消息）极少时，禁止先归因——本集中『模型决策空转』『父级合并计数』『限流』三个假设全部被证据推翻或未证。正确顺序：先用主体自身逐事件日志把轮次按 outcome 分解（opened/settled 分布→主导错误类与状态码→确定性 vs 瞬时），再谈归因。计数范围类问题用定义点一次查证（循环内局部变量置 0、无父级输入=自作用域），并与『主体日志 opened 计数==rounds』互证。子会话数据按 session id 定位其专属日志文件，而非 workspace 级事件流。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:59688c5b-5ae5-42ee-9d63-23685fb569d6:283:181e6784e49a2f0acc94
evidence_refs: learning:learn:2e03ac05def6
created_at: 2026-10-17T20:58:28.307001+08:00
updated_at: 2026-10-17T20:58:28.307001+08:00
---
## Trigger
loop/子代理回执显示 rounds 达到或接近上限（如 outcome=truncated）而真实产出动作（工具执行、入档消息）数量级偏少；或正在争论预算消耗归因（父级合并计数、模型决策空转、限流重试）时。

## Discriminator
回执 payload 自身的数字差距（rounds≈500 vs 工具执行仅十余次）在调查开始前就已可见，它把问题缩成单一未知量：『非产出轮的 outcome 构成是什么』。且主体 session 存在自己的逐事件日志（event_logs/<child_id>.jsonl，按 session id 可直接定位），每轮 provider 调用的 opened/settled/outcome 均有记录——一次分布统计即可裁决所有归因假设。

## Short path
- 从回执数字差定义唯一未知量：非产出轮发生了什么？不要开局做三路线并行宽取证（关键词搜索/action_trace/workspace 流多半不含轮次数据）。
- 按主体 session id 定位其专属事件日志文件（find event_logs/<child_id>），不要查 workspace 级事件流——它常只索引父会话自身轨迹。
- 用行式/JSON 解析统计事件类型与 settled outcome 分布（success/error 计数、错误类名）；多字节 JSONL 忌字节截断 grep。
- 抽取一条完整错误 payload 和成功调用时间线，读 status_code/provider_code/rate_limits/retry_after 字段，区分确定性 4xx 拒绝 vs 瞬时故障/限流。
- 若同时被问计数范围：grep 循环函数内计数器初始化与累加点（局部置 0、父级从不传入=自作用域），再与日志 opened 计数==rounds 互证闭合。
- 命名根因（错误类+状态码+确定性）后即停；更深层未定位项（如具体触发帧）显式声明为遗留问题，不继续宽枚举。

## Stop conditions
- 主导失败类已用状态码/provider_code 命名，且『重发必败的确定性』vs『瞬时/限流』已由 payload 字段区分。
- 计数范围问题已由定义点代码 + 主体日志 opened 计数==rounds 双证据闭合。
- 更深触发帧定位留作独立任务并显式声明，不在本轮继续枚举。

## Verification
- rounds 报告值 == 主体自身日志中 provider.call.opened 的计数。
- 计数器是循环函数局部变量、入口置 0、父级轮次从不传入或累加。
- 错误 payload 的 status_code/provider_code 与最终归因一致；rate_limits 为空、retry_after 为 null 支持『确定性拒绝而非限流』的判定。
- 成功调用的 token 累计与时间分布能解释真实完成的工作量。

## Counterexamples
- rounds 顶满且工具执行数与轮次同量级：这是模型真实决策循环，outcome 分解不改变归因方向，应改查模型策略而非传输层。
- 错误为 429/5xx 且 rate_limits/retry_after 非空：传输层合法重试语义，不构成确定性烧预算，不应得出『缺熔断』结论。
- 主体没有逐事件日志或日志已轮转归档丢失：本方法不适用，退回代码路径分析与带 payload 捕获复现。
- 回执 rounds 远低于上限：不存在预算烧穿问题，不触发本方法。
