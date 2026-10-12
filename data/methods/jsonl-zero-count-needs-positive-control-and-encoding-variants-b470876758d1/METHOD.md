---
method_id: jsonl-zero-count-needs-positive-control-and-encoding-variants-b470876758d1
name: jsonl-zero-count-needs-positive-control-and-encoding-variants
description: 在 JSONL 事件日志中统计某 key=value（如 kind=method）以支撑"零/基线"结论时，原始 grep 会因 payload 嵌套转义而漏计；时间窗过滤选错基址也会产生假零。本方法要求：先用格式必有的键做阳性对照验证 pattern 有效；对目标键同时统计原始与转义两种编码（或直接用 JSON 感知解析器）；窗口计数为 0 时先用文件 mtime 与记录内部时间戳复核窗口基址；对照通过且双编码均为 0，才把零当作发现报告并注明口径。这将"计数方法是否可信"与"现象是否为零"解耦，避免多轮盲试 pattern 与窗口返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1372:971282f2c3305b482d82
evidence_refs: learning:learn:4bb5caa0c2e2
created_at: 2026-09-18T19:25:22.441454+00:00
updated_at: 2026-09-18T19:25:22.441454+00:00
---
## Trigger
需要在可能含嵌套转义 JSON 的 JSONL/事件流中计数特定 key=value，且结果可能为 0 并将作为基线或缺失证据写入结论；或窗口过滤查询返回 0 但与文件时间戳等独立信号矛盾。

## Discriminator
同语料上宽松词频探测大量命中（如 'method' 一词出现 1270 次）而结构化 pattern 计数为 0；或样本记录可见反斜杠转义的嵌套 JSON；或 ls 时间戳显示窗口内存在活跃文件但窗口计数为 0——任一出现即说明零可能是测量伪影而非事实。

## Short path
- 由任务/goal 文本确定测量对象与窗口（已指名 EventStore 切片与 usage 台账），直接定位对应日志源，不先做全目录宽枚举
- 对任一日志文件先用必存在的键（如 event_id/search_records）验证 pattern 命中大于 0，作为阳性对照
- 对目标键同时运行原始与转义两种编码的 pattern（或改用 jq/python 解析后计数），消除嵌套转义漏计
- 窗口计数为 0 时，用文件 mtime 与记录内部时间戳双确认窗口基址后重算，而非直接接受 0
- 阳性对照通过且双编码均为 0，才把"零发现"写入结论并注明统计口径

## Stop conditions
- 阳性对照命中且目标键在原始与转义两种写法下均为 0，零结论成立，停止复查
- 已切换到 JSON 感知解析器得到确定性计数，不再跑 grep 编码变体

## Verification
- 手工取出一条已知含目标键的记录，回灌同一 pattern 确认能命中
- 双编码计数之和与宽松词频探测做量级对账，能解释差异来源（词仅出现在参数文本 vs 真实 occurrence）

## Counterexamples
- 日志为单层 JSON 无嵌套转义时，转义变体是多余开销，单 pattern 即可
- 阳性对照键在该语料中合法为零（新字段/空文件），应换格式必有键而非怀疑方法本身
- 已使用 jq/python 等解码解析器时无需双编码 grep
- 语料极小且目视可穷尽时不必建立对照流程
