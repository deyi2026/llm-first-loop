---
method_id: schema-sample-then-structural-parse-for-jsonl-logs-6c71857ebc2e
name: schema-sample-then-structural-parse-for-jsonl-logs
description: 从机器生成的 JSONL/JSON 事件日志中投影特定字段时，把『真实 schema』当作第一个待解未知量：先直接从文件取一条原始记录确认顶层键与嵌套路径，然后全程用 JSON 解析器按 type/id 结构化过滤投影，不对序列化文本细节（键名猜测、冒号空格、子串位置）做枚举式 grep 试错。若日志同时记录本会话自身消息（message.appended 内含 assistant 消息与 tool_call arguments 原文），任何文本模式都会命中自己的转录，必须用 type/role 结构过滤排除。本集连续三次 grep 变体失败（投影 payload 全 {}、样本抓到自己刚发的话、模式缺空格零命中），改纯 Python 解析后一次成功。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:2732:c9b0c13a66f4150d0028
evidence_refs: learning:learn:097f4466ddf1
created_at: 2026-10-02T09:29:01.368232+08:00
updated_at: 2026-10-02T09:29:01.368232+08:00
---
## Trigger
需要从 .jsonl / JSON 事件日志等机器生成结构化记录中过滤、投影或聚合特定字段，而该日志的确切 schema（顶层键、payload 嵌套路径、序列化风格）尚未经样本确认；或文本检索已出现零命中、字段全空、命中自己消息等信号。

## Discriminator
进入摩擦前后已可见的事实：(1) 目标文件是系统事件记录器产出的 .jsonl（ls 回执可见扩展名），属结构化数据而非自由文本，且 schema 未经验证——这本身就要求『先采样、后解析』；(2) 首次 grep+猜测键投影返回 payload 全为 {}，是『schema 假设错误』的一手信号，此后不应再换 grep 模式；(3) 用 tail 取『最后一条 grep 匹配』当样本，抓到的是 type=message.appended 的本会话 assistant 消息——证明该日志包含当前会话自身，文本子串命中不可信。

## Short path
- tail -n 1（或 head）直接取目标 .jsonl 文件本身的一条完整原始记录并 json.tool 展开：确认真实顶层键（type/ts/payload）与嵌套路径，同时确认日志是否包含本会话自身消息
- 写一个 json.loads 逐行解析脚本：按 type 前缀过滤目标事件，按 attempt/call id 关联 opened/settled，一次投影全部目标字段（含 purpose 等分层字段）
- 对字段缺失的记录按已知版本/重启时间边界分组对比，验证单一根因假设
- 边界两侧字段对照齐全后即停止提取，转入结论与落盘

## Stop conditions
- 目标字段已按记录 id 从结构解析中齐全取出，缺失样本也已按边界归因
- 样本记录显示目标字段根本不在此日志或此 type 中，应转查 schema 来源/生产者代码而非继续换文本模式

## Verification
- 投影用的键路径必须来自实际样本记录而非猜测：抽查一条解析结果与原始行对照
- 子串 grep 只用于定位、不作为字段值来源；任何命中先核对记录的 type/role 是否为目标事件类型，排除本会话 message.appended 污染

## Counterexamples
- 日志确为自由文本（人工编写的 plain-text 日志、无稳定 JSON 结构）：grep/正则本就是正确工具，不必引入解析步骤
- schema 已由权威 schema 文件或生产者代码确认，且目标字段序列化位置稳定：直接 grep 更便宜
- 一次性计数/行数探查、不提取字段：先读样本记录解析 schema 的开销不划算
