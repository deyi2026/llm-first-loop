---
method_id: classify-store-manifest-and-assert-coverage-before-scanning-05a1e53133d7
name: classify-store-manifest-and-assert-coverage-before-scanning
description: 在编写/运行针对目录型事件/日志存储（EventStore、会话日志目录）的扫描或统计脚本前，先用无扩展名过滤的原始清单把存储形态分类（平铺 sid.jsonl、分片 sid/ 目录、孤儿 .lock），对每种形态取样确认布局后再写遍历；首跑必须做覆盖性断言（用已知存在且落在窗口内的事件验证被计入），零结果先怀疑遍历覆盖而非窗口/过滤。避免假性空窗与事后多轮调试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1388:2aa6880be0c51fb62974
evidence_refs: learning:learn:b367b516a987
created_at: 2026-09-18T19:26:43.444785+00:00
updated_at: 2026-09-18T19:26:43.444785+00:00
---
## Trigger
需要编写或运行对目录型事件/日志存储做全量扫描、时间切片统计，或与既有手工基线对比的脚本；或脚本首跑返回全零/空窗口但与已观察事实矛盾。

## Discriminator
无过滤的目录清单中已出现异构形态：某 session 存在 .lock 却无同名 .jsonl、或存在无扩展名的裸 UUID 条目——这证明至少还有第二种存储形态（如 sid/N.jsonl 分片目录）；以及按时间戳前缀的原始 grep 显示窗口内确有事件而脚本计数为 0。

## Short path
- 对目标目录做无扩展名过滤的原始清单，归类条目形态（平铺 .jsonl / 裸 UUID 目录 / 孤儿 .lock）
- 对每种非标准形态取一个样本探测（ls 目录内部、head 分片）确认实际文件布局，再据此写遍历规则
- 定位每个指标的权威字段（如原始参数在 message.appended 的 tool_calls 中，而非只含 sha256 的执行回执）
- 首跑加覆盖断言：选一个已手工读过、确定存在且落在窗口内的事件，断言脚本计入它；通过后才与基线对比
- 零结果且断言失败时，先修遍历覆盖（补分片目录、排除归档等其他存储根），再怀疑窗口/过滤逻辑

## Stop conditions
- 覆盖断言通过：已知存在于窗口内的事件被正确计入，且逐 session 计数之和等于全部存储形态的全库合计
- 目录清单中所有条目形态均被遍历消费（无孤儿 lock、无被跳过的 session）

## Verification
- 用独立原始探针（如按时间戳前缀 grep）复核窗口内事件数与脚本计数一致
- 与既有手工基线差异超阈值时，先核对基线是否来自不同存储根或不同口径，再下修正结论

## Counterexamples
- 目录清单完全同构（每个 lock 恰有同名 .jsonl）：直接 glob 即可，额外形态探测是不必要开销
- 只查单个已知文件（如 usage.jsonl 是否存在）：无需遍历验证
- 窗口确实可能为空（深夜时段、已知无流量）：覆盖断言必须用已验证存在于窗口内的事件，否则不能仅凭零计数反推脚本有错
