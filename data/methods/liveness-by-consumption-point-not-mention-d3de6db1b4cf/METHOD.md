---
method_id: liveness-by-consumption-point-not-mention-d3de6db1b4cf
name: liveness-by-consumption-point-not-mention
description: 代码考古与改造设计前，把 grep 命中、config 参数、pyc 产物、用户口头前提一律视为'提及'而非活性证明。按 定义/消费点/残留 三类给命中分类，用当前消费点（组装/调用处）确立机制活性；发现 del/retired 标记或仅 pyc 命中即推翻原始前提、转向真实活跃面，再对活跃面做用量统计后才进入设计。可避免按已退役面设计，也避免对 pyc 推测出的源码路径连续失败读取。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:327:e2108abe025eed490b6d
evidence_refs: learning:learn:155107074544
created_at: 2026-09-17T15:09:27.008823+00:00
updated_at: 2026-09-17T15:09:27.008823+00:00
---
## Trigger
在对既有系统做改造设计、或要回答'某机制当前如何被使用/承担多少流量'时，手头证据仅来自 grep 命中、config 默认值、__pycache__ 产物、或用户/口头对系统现状的描述。

## Discriminator
每条命中可分三类：定义（存在≠运行）、当前消费点（组装/调用处，是活性唯一证明）、残留（仅 .pyc 命中、无消费者的 config 参数、注明 retired 的注释）。grep 输出里某文件只出现在 __pycache__ 下而无同名 .py、代码里出现 del 参数语句或 'retired/agency-first' 注释，都是活性反证，且这些在最初 grep 结果中即已可见。

## Short path
- 对机制名做 grep 并排除 __pycache__，把每条命中标注为 定义/消费点/残留，明确本轮要解决的未知量是'该机制现在是否在运行'
- 仅 pyc 命中的文件名视为改名/移除线索而非路径：先列目录确认现存源文件再读，禁止按 pyc 名直接 sed 推测路径
- 读当前消费点（组装段/调用处）确认活性；读到 del 参数、retired 注释即判定退役，并据此改写用户原始前提
- 前提修正后，仅对真实活跃面跑量化基线（扫描真实运行产物/会话日志的调用计数）
- 活性结论与用量数据都有代码/数据引用后，才进入设计或拷问，不再按未经消费点支持的口头前提展开

## Stop conditions
- 任务点名的每个机制都有当前消费点代码引用，或都有显式退役证据（del/retired 注释）
- 量化基线已覆盖全部活跃面，结论不再依赖任何无消费点支持的 grep 命中或口头断言

## Verification
- 逐条检查活性结论：引用的是消费点/组装段，而非定义、config 默认值或 pyc 产物
- 退役结论能指出显式标记（del 语句/retired 注释）位置
- 对由 pyc 名推测的源码路径，读取前已确认 .py 文件确实存在（同类 sed 失败不出现第二次）
- 设计文档中被改造的每个面都在已验证的活跃面清单内

## Counterexamples
- 绿地新模块：定义即全部事实，没有历史残留可混淆，无需活性审计
- 闭源二进制或外部服务：源码不可 grep，只能靠运行时探测或文档
- 刻意的 pyc-only 部署（源码在别处仓库）：缺少同名 .py 不等于机制退役
- 该机制活性已在本会话早前验证过：重复审计是浪费而非严谨
