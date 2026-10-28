---
method_id: held-action-id-record-before-state-machine-archaeology-c244c18e01e7
name: held-action-id-record-before-state-machine-archaeology
description: 受管/异步动作（重启、部署、回滚）被追问终态或『要不要再做一次才生效』时，上一轮留下的 durable action_id 就是权威寻址键：先读按它命名的 per-action 持久工件，取终态、时间戳与 failure detail 原文；需要归因阶段时，用 detail 里的独特短语做一次定点 grep 直接落到出错代码行。在读到该记录之前，不要做 repo 级状态字面量检索、通读状态机实现、重复调用已返回稳定结果的 status 端点，也不要在 Evidence 未命中且回执已标明会话级范围后换词重查。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:1678:b9bedcd0492eef717440
evidence_refs: learning:learn:7fd21ccb76bc
created_at: 2026-10-20T10:08:10.997164+08:00
updated_at: 2026-10-20T10:08:10.997164+08:00
---
## Trigger
用户追问上一轮已发起的受管/异步动作（重启/部署/回滚等）的终态、失败原因或『是否需再做一次才生效』，且当前上下文仍持有该动作的 durable action_id，回答依赖这份运行时事实而非源码语义

## Discriminator
手中 action_id 本身就是寻址键：控制面为每个动作落一份以其 ID 命名的 per-action 持久工件（log/record），它是终态与 failure detail 的唯一权威。在读到它之前，repo 级 grep 状态字面量（如 waiting 状态名、超时常量名）、阅读状态机实现函数、重复调用同一 status 端点，都不产生关于『该动作终态』的新事实；Evidence 回执标明『当前会话』范围，即证明对话检索库不含跨轮动作记录，换词重查必然再未命中

## Short path
- 一次控制面 status：用 restart_required、live/desired head 对比与 live 进程启动时间回答『要不要重启才生效』这一半
- 用持有的 action_id 做廉价定点定位：ls 数据目录发现按 ID 命名的 per-action 工件目录（或经处理函数代码定位 store 路径），读取该记录
- 从记录原文取终态、创建/失败时间戳与 failure detail 字面量，闭环『上次动作结果』这一半
- 仅当需要阶段归因时，用 detail 中的独特短语（如超时报错原文）做一次 scoped grep 直落产生该错误的代码行，不预读状态机其余部分、不按猜测的常量名/状态名检索
- 汇总输出『是否需重启+上次为何失败+如何重发』后停止；同一 status 端点二次调用返回与上次逐字节一致，即视为该端点信息已取尽

## Stop conditions
- 两个子问题（是否需重启使生效；上一动作终态与原因）均已由权威记录回答
- failure detail 原文已自含超时秒数与占用原因，无需更多源码归因
- status 重复调用返回与上次一致且无新增字段，继续调用同端点属 post-sufficiency 动作

## Verification
- 终态/时间戳/detail 均引用 per-action 记录原文，而非测试代码或 .releases 快照中的实现片段
- 如给出 file:line 归因，确认该行由 detail 字面量反查命中，而非由猜测的状态名/常量名命中
- 对上一轮说法的更正可逐条追溯到记录字段，而非对话记忆推断

## Counterexamples
- 不持有 action_id、只有『之前好像重启过』的模糊记忆：无法按键寻址，应先查控制面动作台账列表或问用户，此时受限的结构化检索才是合理第一步
- per-action 记录只有退出码、无 detail 原文：记录不足以归因，读 worker 实现才是必要步骤而非绕路
- 用户问题本身是『这个状态机如何实现/如何修改』：源码阅读就是任务目标，不属于本方法适用的绕路场景
- 动作尚未到达终态（仍在 waiting 阶段）：读不到终态，应按两阶段协议安排稍后核验，而不是立即归因失败
