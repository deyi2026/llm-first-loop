---
method_id: repeat-loop-prompt-identity-and-budget-chain-before-guard-code-d304e3a116f5
name: repeat-loop-prompt-identity-and-budget-chain-before-guard-code
description: 排查『模型会话不断重复同一动作』类报告时，证据顺序应为遥测优先、代码其次：先用该会话逐轮请求级遥测比对相邻轮次 prompt 身份（messages_count/history_chars/budget 是否一致），并复算有效输入预算链（窗口→输出预留/注册 max_tokens→工具 schema 占用→剩余对话额度）；若证实『任一回执超剩余额度→压缩归档刚发生的 assistant+tool 交换→prompt 复原→同输入同输出』，即为确定性活锁，根因闭合。守卫/熔断源码只用于解释为何未被拦截（advisory-only、提示位置会被归档），不要在全库搜守卫关键词、扫镜像目录或通读引擎源码之后再回头算预算——那只能解释『没被拦』，解释不了『为何循环』。
aliases: 模型反复调用同一个工具怎么排查, 会话死循环 不断重复 根因, 压缩把新回执归档导致每轮 prompt 一样, 工具 schema 吃满输入预算 循环, agent 复读 诊断顺序 遥测优先, 同输入同输出 确定性活锁
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc3e7780-af3b-4ea4-97e2-85cec88dbb96:99:f53ae49fe110d59041ae
evidence_refs: learning:learn:abba2bf78de8
created_at: 2026-11-14T20:25:49.677474+08:00
updated_at: 2026-11-14T20:25:49.677474+08:00
---
## Trigger
用户报告某会话/本地模型『不断重复』，且事件流或回执已给出机械事实：同 (tool, 精确参数) 的 repeat/观测事件（exact_call_count≥3）、伴随 high_context_pressure、观测事件 prompt_chars=0，或逐轮预算遥测与模型注册表声明的窗口口径对不上。

## Discriminator
动手查代码前已可见的判别事实：①重复是精确参数级且伴随 high_context_pressure（重复与上下文压力同现，指向 prompt 复原而非模型随机）；②观测/守卫事件 prompt_chars=0（提示不进 prompt，纯 advisory）；③预算遥测单值与 catalog 声明窗口无法对账（预算口径本身可疑）。三者合取在第一次代码搜索之前就足以把假设缩为『每轮 prompt 被复原的预算活锁』，而判据全部在逐轮遥测里，不需要先读引擎源码。

## Short path
- 拉该会话事件流，定位重复的具体 (tool,args) 与伴随 reasons（repeated_exact_call / high_context_pressure）；未知量：重复是确定性还是随机？
- 水合连续 2~3 轮的请求级遥测，逐字节比对 prompt 身份字段（messages_count、history_chars、budget）；未知量：每轮输入是否相同？
- 复算预算链：窗口→输出预留/注册 max_tokens→工具 schema tokens→剩余对话额度；验证『回执字符数>剩余额度→压缩归档刚发生的交换→prompt 复原』闭环；未知量：活锁机制是否成立？
- 机制成立后，仅按遥测点名的守卫符号定点读源码，确认 advisory-only 与提示注入位置（为何提示从未活到下一次决策）；未知量：为何未拦截？
- 对照模型注册项（window/max_tokens/工具数）定位错配项，输出修复方案并把未核验项单列；停止。

## Stop conditions
- 已证实相邻轮次 prompt 逐字节相同 + 预算链闭环（回执>剩余额度→归档新交换）+ 守卫语义核实 → 根因闭合，停止探索，写修复方案
- 任两轮 prompt 或工具参数实际不同 → 确定性活锁假设被证伪，转随机性/模型侧/传输重试假设，不再沿预算链走

## Verification
- 至少抽 2 轮请求级字段比对一致，才允许下『同输入→同输出』的确定性结论
- 预算链各分段（窗口、输出预留、工具 schema、剩余额度）相加须等于实发额度；日志单一预算数字与实发不符时以链为准，并写明口径差
- 守卫源码的阻断性与提示注入位置须与『提示未影响下一轮决策』的遥测事实互证

## Counterexamples
- 各轮 prompt 或工具参数实际不同（模型在换措辞/换参数探索）→ prompt 身份比对即失败，应查采样温度、提示词或模型能力，而非预算链
- 重复由上游 5xx/超时触发客户端自动重试 → 事件流先出现传输错误类，按错误归因，不适用本方法
- 运行时未插桩逐轮 prompt/budget 字段 → 无遥测可比，先复现并加插桩，再谈归因
- 小模型纯文本复读退化（非工具调用级精确重复）→ 已知模型缺陷，调预算无效
