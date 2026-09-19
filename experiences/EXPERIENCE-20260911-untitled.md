---
title: "\"零检索\"是检索面假象：审计全称命题先穷尽检索面；开局门试点挂任务验收而非全局协议"
scenario: "跨会话库（method/experience/rule）使用率审计。早晨会话用窄查询（候选哈希 + 单一方法名 + 事件流 limit=30）得出\"跨会话零检索、库读侧死了\"的全称结论；全量复验（event_stream since=09-10 + kind=all 查哈希 + 读回截断中段）发现：昨日多会话存在 kind=experience/method/rule/evolution/memory/all 的密集任务关键词检索，且候选对象实为 GOAL/TASK 而非库条目。真实缺口是时序与留痕，不是检索本身。"
root_cause: "检索面窄（哈希/单名/30条窗口）叠加\"命中为空=证据\"的推断；action_trace 30 条上限只覆盖约 30 分钟，极易把\"窗口外有记录\"读成\"从未发生\""
solution: "1) 全称\"零\"必须先复验：event_stream(query=search_records, since=足够早, limit=100+) 看全量 + search_records(kind=all, query=目标指纹) 定位对象本体 + read_evidence 补截断中段；2) 缺口应重新表述为\"开局装载+逐条裁决留痕\"，对策挂 task acceptance（开局一次有界检索+回复含逐行裁决），不造全局新协议；3) 留痕复用 action_trace：search_records 调用即天然回执，无需新增仪式；4) 试点必须带死线与 invalidate 标准，度量用 检索→裁决→采用 漏斗，不用单一方法使用率当对照（触发面不可比）"
evidence: "event_stream since=2026-09-10T00:00Z query=search_records limit=100 全文（evidence://v1/6a144fb0f3561bf12041a1e6120e313b5e664eab805be414c56158839bdadb0e）；search_records kind=all query=candidate-a80acb208b99 命中 task_create/declaration_check/episode；morning 窄审计：event_stream limit=30 + kind=method query=单名 + 候选哈希 → 假零"
tags: [retrieval-audit, base-rate, opening-gate, task-acceptance, falsifiable-pilot, meta-lesson, false-zero]
source: {}
status: active
created_at: "2026-09-11T14:28:53.942605+08:00"
updated_at: "2026-09-11T14:28:53.942605+08:00"
---