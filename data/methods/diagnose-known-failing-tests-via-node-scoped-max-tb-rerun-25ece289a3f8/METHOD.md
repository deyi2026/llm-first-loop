---
method_id: diagnose-known-failing-tests-via-node-scoped-max-tb-rerun-25ece289a3f8
name: diagnose-known-failing-tests-via-node-scoped-max-tb-rerun
description: 权威回执已列出精确失败节点后，诊断重跑必须按节点最小化并预选能穿透固定输出噪声的详细度。本集在拿到含精确 FAILED 节点的全量回执后，先做了文件级批量 + 低细节(--tb=short/line)重跑，回执被仓库固定 46 行 audit 告警块淹没并截断，断言正文不可见，被迫多次重复调用；直到改为单用例 --tb=long 才直接读到根因（精确环边、env 残留键名）。可程序化：解析回执 FAILED 行构造单节点命令；回执含固定噪声签名或截断且无断言行 → 立即升级单用例最大详细度，不做同粒度重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1267:1068b4e14e21c5060b5a
evidence_refs: learning:learn:655db55cfc69
created_at: 2026-09-30T00:45:31.598537+08:00
updated_at: 2026-09-30T00:45:31.598537+08:00
---
## Trigger
已有一份权威测试回执（精确 FAILED 节点 ID 在手），需要对各失败诊断根因；或上一条诊断回执被固定告警块/截断淹没、未含可读断言内容。

## Discriminator
knowledge-at-time：回执中已存在精确失败节点 ID（tests/unit/...::test_x）；随后诊断回执出现固定噪声块与截断标记，证明该输出通道下『文件级 + 低 traceback』的重跑不可能缩小『为何失败』这个未知量——当时即可预判应直接单节点 + 高详细度。

## Short path
- 从权威回执提取精确失败节点 ID 清单，不重跑全量、不按文件批量诊断
- 按失败模式分组，对每组构造单节点命令，并预置输出过滤或直接 --tb=long
- 回执若含固定噪声块/截断且无断言行 → 立即改单用例 --tb=long，不重复同粒度命令
- 根因可读后做最小修复，仅重跑该节点验证转绿
- 全部节点修复后跑一次全量收口，得到 0 failed 即停止

## Stop conditions
- 每个失败节点的断言/根因已从回执中直接可读
- 修复后对应节点单独重跑通过
- 最终全量回执 0 failed，与修复清单计数一致

## Verification
- 诊断命令的目标节点必须与回执 FAILED 行逐一对应（机械可核对）
- 每条诊断回执必须能指认出断言行；指认不出即视为无效调用并升级详细度，而不是原样重发
- 最终全量回执的 passed/failed 计数与所修节点数一致（本集 6 节点 + 1 处顺手发现的 ledger 项）

## Counterexamples
- 尚无权威失败清单时：先跑一次全量拿名单是正确第一步（本集首步即属此类，不因本方法跳过）
- 输出通道无固定噪声且低细节断言自解释（本集 resolved_episode 的一行断言即可定位泄漏串）：此时批量 --tb=line 更省，不必强行单节点 --tb=long
- 疑似测试间污染 / env 泄漏类失败，单节点隔离可能无法复现：需按文件/模块级重跑，但即便升粒度也应保持足够 traceback 详细度，方法只约束『范围升级』不约束『详细度降级』
