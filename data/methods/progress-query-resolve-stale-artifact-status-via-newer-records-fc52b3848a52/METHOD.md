---
method_id: progress-query-resolve-stale-artifact-status-via-newer-records-fc52b3848a52
name: progress-query-resolve-stale-artifact-status-via-newer-records
description: 现状类提问（『X 进行得怎么样』）下，已定位权威工件内的 status 字段只是写作时快照：当存在可观测陈旧信号（记忆记录的行数/时间与实际文件不符、get_goal 无活动目标但文档写『待实施』、工件头部自钉基线日期/generation）时，不要据此做全库文件名枚举（只会命中 .releases 快照噪声）或对同一记录库换措辞重查；应直接查晚于工件写作锚的事件/goal/交付记录，沿 trace 中点名的交付报告一次取得终态并作答。本集 12 次调用中约 4 次（文件名枚举、变体重查记录库、二次重读同文档、无关 stat）可省。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e729d08f-6ec8-459b-b3be-a3eb65be8025:0:f2e10c9a27bf65215c94
evidence_refs: learning:learn:277e81b66f51
created_at: 2026-10-13T21:51:47.222955+08:00
updated_at: 2026-10-13T21:51:47.222955+08:00
---
## Trigger
用户询问某具名工作项的当前进展；已读到的权威工件（设计文档/记忆记录）自带 status 字段与写作时间锚（定稿日期、核验基线 generation、记录时行数/大小）；且存在锚后仍有活动的可观测信号（实际文件行数/大小与记录值不符、get_goal 无活动 goal、或已知存在更晚的 action trace）。

## Discriminator
『文档 status=待实施』与『get_goal 无活动目标』只能由『未开工』或『已完工并关闭 goal』之一解释，而记忆记录的 347 行 ≠ 实际文件 355 行证明工件在记录之后仍被修改——现值必然存在于晚于工件写作锚的事件/goal/交付记录中；文件名枚举与同库换词重查都不提供时间维信息，无法消解这个张力。

## Short path
- 从记忆/记录定位具名工件并读其头部 status 与写作锚（日期/基线 generation）；未知量：计划内容与工件自称状态。
- 识别陈旧信号（记录行数≠实际、无活动 goal 与『待实施』相张力）→ 判定 status 为写作时快照；未知量：写作锚之后发生了什么。
- 查询事件/goal 时间线中晚于工件 mtime 的条目；未知量：已开工还是已完工。
- 读取 trace 中点名的交付/终态报告；未知量：实际结果与 commit 证据。
- 交叉核对 commit/generation 与时间戳后，以带时间戳事实作答，并指出文档 status 已被后续交付取代。

## Stop conditions
- 终态报告引用的 commit/generation 与事件流时间戳交叉一致，且与『无活动 goal』自洽 → 现状已证实，停止发现。
- 工件写作锚之后不存在任何更新的记录/事件 → 文档 status 即现值，直接作答。

## Verification
- 交付报告的 commit/generation 与 event_stream 时间戳逐条对得上。
- 答案把文档 status 字段显式标注为写作时快照、已被后续交付取代，结论用带时间戳表述而非终局断言。

## Counterexamples
- status 字段由活进程实时回写（看板/CI 维护），或工件落笔后确无任何新事件 → 文档即现值，查时间线属浪费。
- 用户问的是设计内容本身而非进展 → 读文档即停，不需要时间线。
- 环境没有事件/goal 记录系统 → 时间线来源应改为 git log 与文件 mtime，而非记录库或文件名枚举。
